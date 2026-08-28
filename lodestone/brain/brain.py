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
                uri=uri, tags=tags or [],
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
    def recall(self, query: str, *, limit: int = 8, max_tokens: int = 1400,
               source: str | None = None) -> dict[str, Any]:
        """Fuse graph + vector recall into an injectable context block."""
        hits = self.store.search(query, limit=limit, source=source)
        ents = self.graph.match_entities(query, limit=4)

        graph_lines: list[str] = []
        for e in ents:
            facts = self.graph.facts_for(e["id"], limit=4)
            head = f"• {e['name']} ({e['type']})"
            if e["summary"]:
                head += f": {e['summary']}"
            graph_lines.append(head)
            graph_lines += [f"    - {f}" for f in facts]

        budget = max_tokens * _CHARS_PER_TOKEN
        blocks: list[str] = []
        used = 0
        kept = []
        for h in hits:
            block = h.memory.as_context()
            if used + len(block) > budget and blocks:
                break
            blocks.append(block)
            used += len(block)
            kept.append(h)

        parts = []
        if graph_lines:
            parts.append("KNOWN ENTITIES & FACTS:\n" + "\n".join(graph_lines))
        if blocks:
            parts.append("RELEVANT MEMORIES:\n" + "\n\n---\n\n".join(blocks))
        context = ""
        if parts:
            context = (
                "Context recalled from the user's personal Lodestone brain. "
                "Use it to act without asking them to repeat themselves.\n\n"
                + "\n\n".join(parts)
            )
        return {
            "context": context,
            "memory_hits": [{"score": h.score, **h.memory.model_dump()} for h in kept],
            "entities": ents,
        }

    def stats(self) -> dict[str, Any]:
        s = self.store.stats()
        s["graph"] = self.graph.stats()
        return s


@lru_cache
def get_brain() -> Brain:
    return Brain()
