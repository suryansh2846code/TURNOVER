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

    def recall(self, query: str, *, limit: int = 8, max_tokens: int = 1400,
               source: str | None = None, prefer: list[str] | None = None) -> dict[str, Any]:
        """Fuse graph + vector recall into an injectable context block.

        If the query references a date/range ("emails on July 14", "last week"),
        recall is filtered to items whose real event_date falls in that range.
        """
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
        date_note = ""
        if dr:
            date_note = (f"[Date filter applied: showing only items dated "
                         f"{date_start}"
                         + (f" to {date_end}" if date_end != date_start else "")
                         + (". Nothing in the brain matches that date."
                            if not kept else ".") + "]\n")
        if parts or date_note:
            context = (
                "Context recalled from the user's personal Lodestone brain. "
                "Use it to act without asking them to repeat themselves.\n\n"
                + date_note
                + "\n\n".join(parts)
            )
        return {
            "context": context,
            "memory_hits": [{"score": h.score, **h.memory.model_dump()} for h in kept],
            "entities": ents,
            "date_range": dr,
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
