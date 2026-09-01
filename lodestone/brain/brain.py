"""The Brain: one continuously-updated knowledge base shared by all agents.

Combines a vector memory store (raw recallable chunks) with a knowledge graph
(entities + facts). Ingestion writes both; recall fuses both into a compact,
ready-to-inject context block — so any agent, on any model, starts already
knowing the user.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..core.chunk import chunk_text
from ..core.store import MemoryStore, get_store
from . import extract as extractor
from .graph import GraphStore

_CHARS_PER_TOKEN = 4


class Brain:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_store()
        self.graph = GraphStore(self.store)

    # ── ingestion ────────────────────────────────────────────────────────
    def ingest(self, text: str, *, source: str = "manual", kind: str = "note",
               title: str | None = None, uri: str | None = None,
               build_graph: bool = True, fast: bool = False,
               event_date: str | None = None, metadata: dict | None = None,
               tags=None) -> dict[str, Any]:
        """Ingest text into both the vector store and the knowledge graph.

        `fast=True` uses offline heuristic extraction only (no per-chunk LLM
        call) — used for bulk connector syncs so importing a whole folder stays
        quick instead of hitting the model hundreds of times.
        """
        added_mem = 0
        entities = 0
        facts = 0
        for i, chunk in enumerate(chunk_text(text)):
            mem = self.store.add(
                text=chunk, source=source, kind=kind,
                title=title if i == 0 else f"{title} (part {i+1})" if title else None,
                uri=uri, tags=tags or [], event_date=event_date,
                metadata=metadata,
            )
            if not mem:
                continue
            added_mem += 1
            if build_graph:
                e, f = self._graph_from(chunk, mem.id, fast=fast)
                entities += e
                facts += f
        return {"memories": added_mem, "entities": entities, "facts": facts}

    def _graph_from(self, text: str, mem_id: str, fast: bool = False) -> tuple[int, int]:
        data = (extractor.extract_heuristic(text) if fast
                else extractor.extract(text))
        name_to_id: dict[str, str] = {}
        for ent in data.get("entities", []):
            eid = self.graph.upsert_entity(
                ent.get("name", ""), type=ent.get("type", "thing"),
                summary=ent.get("summary", ""),
            )
            if eid:
                name_to_id[ent["name"]] = eid
        n_facts = 0
        for fact in data.get("facts", []):
            subj = name_to_id.get(fact.get("subject", ""))
            if not subj:
                # create the subject entity on the fly if referenced
                if fact.get("subject"):
                    subj = self.graph.upsert_entity(fact["subject"])
                    name_to_id[fact["subject"]] = subj
            obj = name_to_id.get(fact.get("object") or "")
            self.graph.add_relation(
                subj or "", fact.get("predicate", "related_to"), obj,
                fact.get("fact", ""), source_mem=mem_id,
            )
            if subj:
                n_facts += 1
        return len(name_to_id), n_facts

    # ── recall ───────────────────────────────────────────────────────────
    # keyword → (source, human label) for "what's in my X" overview queries
    _SOURCE_KW = [
        (("inbox", "email", "emails", "mail", "mails", "gmail"), "gmail", "Gmail"),
        (("drive", "google drive", "document", "documents", "docs"), "gdrive", "Google Drive"),
        (("calendar", "event", "events", "meeting", "meetings", "schedule"), "gcal", "Calendar"),
        (("message", "messages", "imessage", "texts"), "imessage", "iMessage"),
        (("notion",), "notion", "Notion"),
    ]
    _OVERVIEW_RE = None

    def _overview(self, query: str):
        """If the query asks 'what's in / summarize / list my <source>', return
        (source, label, listing-block); else None. Lists the items of that source
        so the agent can answer overview questions semantic search can't."""
        import re
        if self._OVERVIEW_RE is None:
            Brain._OVERVIEW_RE = re.compile(
                r"\b(what'?s?\s+in|summar|list|show me|overview|everything|"
                r"all (my|the)|what do i have|do i have (any|some)|contents? of|"
                r"how many|go through|run through)\b", re.I)
        q = query.lower()
        if not self._OVERVIEW_RE.search(q):
            return None
        for kws, src, label in self._SOURCE_KW:
            if any(re.search(rf"\b{re.escape(k)}\b", q) for k in kws):
                # DISTINCT files/emails — group by uri (or title) so multi-chunk
                # PDFs count once, not once per chunk.
                rows = self.store._conn.execute(
                    "SELECT title, uri, MAX(event_date) AS d FROM memories "
                    "WHERE source=? GROUP BY COALESCE(uri, title) "
                    "ORDER BY d DESC, MAX(created_at) DESC LIMIT 200",
                    (src,),
                ).fetchall()
                seen, titles = set(), []
                for r in rows:
                    base = (r["title"] or "").split(" (part")[0].strip()
                    if base and base.lower() not in seen:
                        seen.add(base.lower())
                        titles.append((r["d"], base))
                if not titles:
                    return (src, label, f"You have NO {label} items in the brain yet.")
                shown = titles[:60]
                lines = [f"- {t}" + (f"  ({d})" if d else "") for d, t in shown]
                more = f"\n…and {len(titles) - len(shown)} more" if len(titles) > len(shown) else ""
                block = (f"OVERVIEW — the user's {label} in the brain "
                         f"({len(titles)} items):\n" + "\n".join(lines) + more)
                return (src, label, block)
        return None

    # detect "find/get a document" intent for on-demand Drive fetch
    _FIND_RE = None
    _DOC_RE = None
    _FIND_STOP = {
        "find", "get", "pull", "fetch", "open", "show", "locate", "bring", "give",
        "me", "my", "the", "a", "an", "of", "in", "from", "on", "for", "please",
        "can", "you", "do", "have", "is", "there", "where", "wheres", "search",
        "file", "files", "doc", "docs", "document", "documents", "pdf", "note",
        "notes", "sheet", "slides", "slide", "presentation", "drive", "google",
        "folder", "and", "all", "any", "some", "this", "that", "year", "notess",
    }

    def _find_terms(self, query: str):
        import re
        if self._FIND_RE is None:
            Brain._FIND_RE = re.compile(
                r"\b(find|get|pull|fetch|open|show|locate|bring|where'?s?|"
                r"do you have|is there|search)\b", re.I)
            Brain._DOC_RE = re.compile(
                r"\b(file|files|doc|docs|document|documents|pdf|notes?|resume|cv|"
                r"sheet|slides?|presentation|drive|email|emails|mail|mails|inbox|"
                r"message|messages)\b", re.I)
        if not (self._FIND_RE.search(query) and self._DOC_RE.search(query)):
            return None
        words = [w for w in re.findall(r"[a-z0-9@.]{2,}", query.lower())
                 if w not in self._FIND_STOP]
        return " ".join(words[:5]) if words else None

    def _maybe_fetch(self, query: str):
        """On-demand fetch: if the user asks for a specific email/document not in
        the brain, live-search the right source (Gmail or Drive) and ingest it.
        Returns (fetched_titles, source)."""
        import re
        terms = self._find_terms(query)
        if not terms:
            return [], ""
        from ..connectors import REGISTRY, get_connector
        # route by what the user mentioned
        if re.search(r"\b(email|emails|inbox|mail|mails|gmail|sent|from)\b",
                     query.lower()):
            src, kw = "gmail", "max_results"
        else:
            src, kw = "gdrive", "max_files"
        cls = REGISTRY.get(src)
        if not cls or not cls().is_configured()[0]:
            return [], ""
        conn = get_connector(src)
        fetched = conn.search_and_ingest(terms, **{kw: 8 if src == "gmail" else 5})
        return fetched, src

    def _escape_hatch(self, query: str):
        """For all-history/aggregate questions, note that only a recent window is
        indexed and offer to sync the full archive; trigger it if the user asks."""
        import re
        ql = query.lower()
        if not re.search(r"\b(email|emails|inbox|mail|mails)\b", ql):
            return ""
        # explicit request → kick off a full-history sync in the background
        if re.search(r"\bsync\b.*\b(all|full|entire|everything)\b", ql) or \
           re.search(r"\b(all|full|entire)\b.*\b(email|mail|inbox|archive)\b.*\bsync\b", ql):
            import threading
            from ..connectors import get_connector
            threading.Thread(
                target=lambda: get_connector("gmail").sync(full_history=True),
                daemon=True).start()
            return ("[Started syncing the user's FULL email archive in the "
                    "background — tell them it's indexing and will be ready shortly.]\n")
        # aggregate/all-history intent → offer the escape hatch
        if re.search(r"\b(all my|entire|whole|every|all[- ]time|top senders?|"
                     r"how many|last year|this year|overall|in total)\b", ql):
            return ("[NOTE: for speed, only recent mail (~last 90 days) is indexed. "
                    "This is an all-history/aggregate question, so answer from what's "
                    "here and OFFER to sync the full archive — the user can say "
                    "'sync all my email' or use the Connectors panel.]\n")
        return ""

    def recall(self, query: str, *, limit: int = 8, max_tokens: int = 1400,
               source: str | None = None, prefer: list[str] | None = None) -> dict[str, Any]:
        """Fuse graph + vector recall into an injectable context block.

        If the query references a date/range ("emails on July 14", "last week"),
        recall is filtered to items whose real event_date falls in that range.
        Also lazily fetches a requested document from Drive if it isn't yet in
        the brain, then includes it.
        """
        fetched, fetched_src = self._maybe_fetch(query)   # on-demand Gmail/Drive
        hatch_note = self._escape_hatch(query)            # all-history escape hatch

        from ..core.dateparse import parse_date_range
        dr = parse_date_range(query)
        date_start, date_end = dr if dr else (None, None)

        # "what's in my drive/inbox/calendar" → a listing, which semantic search
        # can't produce. Inject an overview of that source and prefer it.
        ov = self._overview(query)
        overview_block = ""
        if ov:
            ov_src, _ov_label, overview_block = ov
            prefer = list(set((prefer or []) + [ov_src]))

        # a dated query usually wants MORE of that day's items, so widen the window
        eff_limit = 25 if dr else limit
        hits = self.store.search(
            query, limit=eff_limit, source=source, prefer=prefer,
            date_start=date_start, date_end=date_end)
        ents = self.graph.match_entities(query, limit=4)

        graph_lines: list[str] = []
        for e in ents:
            facts = self.graph.facts_for(e["id"], limit=4)
            head = f"• {e['name']} ({e['type']})"
            if e["summary"]:
                head += f": {e['summary']}"
            graph_lines.append(head)
            graph_lines += [f"    - {f}" for f in facts]

        # For a dated query the user usually wants an OVERVIEW of that period, so
        # render each item compactly (so all of the day's emails fit) and widen
        # the budget; otherwise keep full-context blocks for depth.
        compact = dr is not None
        budget = max_tokens * (3 if compact else 1) * _CHARS_PER_TOKEN
        blocks: list[str] = []
        used = 0
        kept = []
        for h in hits:
            if compact:
                m = h.memory
                head = (m.title or m.text[:60]).strip()
                snippet = " ".join(m.text.split())[:200]
                block = f"• [{m.event_date or m.source}] {head} — {snippet}"
            else:
                block = h.memory.as_context()
            if used + len(block) > budget and blocks:
                break
            blocks.append(block)
            used += len(block)
            kept.append(h)

        parts = []
        if overview_block:                       # source listing first
            parts.append(overview_block)
        if graph_lines and not compact:
            parts.append("KNOWN ENTITIES & FACTS:\n" + "\n".join(graph_lines))
        if blocks:
            label = ("ITEMS IN THAT DATE RANGE:" if compact else "RELEVANT MEMORIES:")
            joiner = "\n" if compact else "\n\n---\n\n"
            parts.append(label + "\n" + joiner.join(blocks))
        context = ""
        fetch_note = ""
        if fetched:
            where = "Gmail" if fetched_src == "gmail" else "Drive"
            fetch_note = (f"[Just fetched from {where} on demand: "
                          + ", ".join(fetched[:8]) + "]\n")
        fetch_note += hatch_note
        date_note = ""
        if dr:
            date_note = (f"[Date filter applied: showing only items dated "
                         f"{date_start}"
                         + (f" to {date_end}" if date_end != date_start else "")
                         + (". Nothing in the brain matches that date."
                            if not kept else ".") + "]\n")
        if parts or date_note or fetch_note:
            context = (
                "Context recalled from the user's personal Lodestone brain. "
                "Use it to act without asking them to repeat themselves.\n\n"
                + fetch_note + date_note
                + "\n\n".join(parts)
            )
        return {
            "context": context,
            "memory_hits": [{"score": h.score, **h.memory.model_dump()} for h in kept],
            "entities": ents,
            "date_range": dr,
            "fetched": fetched,
        }

    _PROSE_EXT = (".md", ".markdown", ".txt", ".rst", ".org")

    def _is_prose(self, mem) -> bool:
        # The knowledge graph is the user's CURATED knowledge — notes, facts,
        # and prose docs. Bulk email (HTML boilerplate) and Drive files are noisy,
        # so they stay fully searchable as memories but do NOT build the graph.
        if mem.source in {"notes", "agent", "manual", "notion"}:
            return True
        if mem.uri and mem.uri.lower().endswith(self._PROSE_EXT):
            return True
        return mem.kind in {"note", "fact"}

    def rebuild_graph(self) -> dict[str, Any]:
        """Wipe the knowledge graph and re-extract it from prose memories only,
        applying the current (stricter) extractor. Fixes graphs built by older,
        looser extraction; leaves searchable memories untouched."""
        with self.store._lock:
            self.store._conn.execute("DELETE FROM relations")
            self.store._conn.execute("DELETE FROM entities")
            self.store._conn.commit()
        entities = facts = scanned = 0
        offset = 0
        while True:
            batch = self.store.list(limit=500, offset=offset)
            if not batch:
                break
            for mem in batch:
                if not self._is_prose(mem):
                    continue
                e, f = self._graph_from(mem.text, mem.id, fast=True)
                entities += e
                facts += f
                scanned += 1
            offset += len(batch)
        return {"scanned_prose_memories": scanned,
                "entities": self.graph.stats()["entities"],
                "facts": self.graph.stats()["relations"]}

    def run_migrations(self) -> dict[str, Any]:
        """Auto-migrate derived data when the code version changed — so every
        user's brain upgrades itself on startup, with no manual re-embed/rebuild.
        Idempotent: a no-op when versions already match."""
        from . import extract as extractor
        store = self.store
        done: dict[str, Any] = {}

        if store.count() == 0:
            return done

        # 1) embeddings: re-embed everything if the embedder (model/dim) changed
        cur_sig = store.embedder_signature()
        if store.get_meta("embedder_sig") != cur_sig:
            done["reembedded"] = store.reembed_all()
            store.set_meta("embedder_sig", cur_sig)

        # 2) knowledge graph: rebuild if the extractor version changed
        if store.get_meta("extractor_version") != extractor.EXTRACTOR_VERSION:
            g = self.rebuild_graph()
            done["graph_rebuilt"] = g.get("entities")
            store.set_meta("extractor_version", extractor.EXTRACTOR_VERSION)

        return done

    def export(self) -> dict[str, Any]:
        """A portable snapshot of the whole brain — the user owns their data and
        can back it up or move it to another machine."""
        from datetime import datetime, timezone
        mems = self.store.export_all()
        return {
            "lodestone_backup": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(mems),
            "memories": mems,
        }

    def import_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Restore memories from an export. Dedup makes it idempotent (re-importing
        the same backup adds nothing), and the graph is rebuilt afterward."""
        mems = (data or {}).get("memories", [])
        if not isinstance(mems, list):
            return {"added": 0, "skipped": 0, "error": "no 'memories' list found"}
        added = 0
        for m in mems:
            if not isinstance(m, dict) or not (m.get("text") or "").strip():
                continue
            saved = self.store.add(
                text=m["text"], source=m.get("source") or "import",
                kind=m.get("kind") or "note", title=m.get("title"),
                uri=m.get("uri"), tags=m.get("tags") or [],
                event_date=m.get("event_date"), metadata=m.get("metadata") or {},
            )
            if saved:
                added += 1
        g = self.rebuild_graph() if added else {"entities": 0}
        return {"added": added, "skipped": len(mems) - added,
                "entities": g.get("entities", 0)}

    def reembed(self) -> dict[str, Any]:
        """Recompute all vectors (memories + entities) with the current embedder.
        Run after switching LODESTONE_EMBEDDING_PROVIDER."""
        n = self.store.reembed_all()
        g = self.rebuild_graph()   # re-extracts + re-embeds entities too
        return {"reembedded_memories": n, "graph_entities": g["entities"]}

    def stats(self) -> dict[str, Any]:
        s = self.store.stats()
        s["graph"] = self.graph.stats()
        return s


@lru_cache
def get_brain() -> Brain:
    return Brain()
