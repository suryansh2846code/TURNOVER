"""The memory store: the local 'brain'.

Persists memories to SQLite with their embeddings and provides semantic +
lexical recall over them. Vectors are stored as float32 blobs and searched with
NumPy — no external vector DB needed, and it comfortably handles tens of
thousands of memories on a laptop.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from functools import lru_cache
from typing import Any, Iterable

import numpy as np

from ..config import get_settings
from .db import connect
from .embeddings import get_embedder
from .models import Memory, RecallHit


def _content_hash(text: str, uri: str | None) -> str:
    h = hashlib.sha256()
    h.update((uri or "").encode())
    h.update(b"\x00")
    h.update(text.strip().encode())
    return h.hexdigest()


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        text=row["text"],
        source=row["source"],
        kind=row["kind"],
        title=row["title"],
        uri=row["uri"],
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        event_date=row["event_date"] if "event_date" in row.keys() else None,
    )


class MemoryStore:
    def __init__(self, db_path=None) -> None:
        settings = get_settings()
        from pathlib import Path
        self.db_path = Path(db_path) if db_path else settings.db_path
        self._conn = connect(self.db_path)
        self._lock = threading.Lock()
        self._embedder = get_embedder()
        # in-memory vector cache for fast recall
        self._vecs: np.ndarray | None = None
        self._ids: list[str] = []
        self._dirty = True

    # ── writing ────────────────────────────────────────────────────────────
    def add(
        self,
        text: str,
        *,
        source: str = "manual",
        kind: str = "note",
        title: str | None = None,
        uri: str | None = None,
        tags: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
        event_date: str | None = None,
    ) -> Memory | None:
        """Add one memory. Returns None if it is a duplicate (same content+uri)."""
        text = (text or "").strip()
        if not text:
            return None
        mem = Memory(
            id=str(uuid.uuid4()),
            text=text,
            source=source,
            kind=kind,
            title=title,
            uri=uri,
            tags=list(tags or []),
            event_date=event_date,
            metadata=metadata or {},
        )
        chash = _content_hash(text, uri)
        # Skip all work if we already have this exact content — makes repeated
        # (background) syncs cheap: no re-embedding of unchanged items.
        if self._conn.execute(
            "SELECT 1 FROM memories WHERE content_hash=?", (chash,)
        ).fetchone():
            return None
        vec = self._embedder.embed_one(text)
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO memories
                       (id, text, source, kind, title, uri, tags, metadata,
                        created_at, updated_at, embedding, embed_dim, embed_model,
                        content_hash, event_date)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mem.id, mem.text, mem.source, mem.kind, mem.title, mem.uri,
                        json.dumps(mem.tags), json.dumps(mem.metadata),
                        mem.created_at, mem.updated_at,
                        vec.tobytes(), len(vec), self._embedder.name, chash,
                        mem.event_date,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return None  # duplicate content_hash
            self._dirty = True
        return mem

    def add_many(self, items: list[dict[str, Any]]) -> int:
        added = 0
        for item in items:
            if self.add(**item):
                added += 1
        return added

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            self._conn.commit()
            self._dirty = True
            return cur.rowcount > 0

    def delete_source(self, source: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE source=?", (source,))
            self._conn.commit()
            self._dirty = True
            return cur.rowcount

    # ── reading ──────────────────────────────────────────────────────────
    def get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)
        ).fetchone()
        return _row_to_memory(row) if row else None

    def list(
        self, *, source: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Memory]:
        if source:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE source=? "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (source, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def export_all(self) -> list[dict[str, Any]]:
        """Every memory as a portable dict (no vectors — re-embedded on import,
        so a backup survives an embedder change or a move to another machine)."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            rows = self.list(limit=500, offset=offset)
            if not rows:
                break
            for m in rows:
                out.append({
                    "text": m.text, "source": m.source, "kind": m.kind,
                    "title": m.title, "uri": m.uri, "tags": m.tags,
                    "event_date": m.event_date, "metadata": m.metadata,
                })
            offset += len(rows)
        return out

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]

    # ── knowledge-graph enrichment queue ─────────────────────────────────
    # graphed levels: 0 = untouched · 1 = heuristic pass done (auto, free) ·
    #                 2 = LLM-enriched (rich). Heuristic queue = graphed<1,
    #                 LLM queue = graphed<2 (so the LLM can upgrade heuristic work).
    def _cap_cte(self, below: int, cap: int, full: tuple) -> tuple[str, list]:
        """Subquery that caps bulk sources to their most-recent `cap` memories,
        while `full` sources (calendar/notes…) are always included in full."""
        ph = ",".join("?" for _ in full) or "''"
        sql = (f"SELECT * FROM (SELECT *, CASE WHEN source IN ({ph}) THEN 0 ELSE "
               "ROW_NUMBER() OVER (PARTITION BY source ORDER BY created_at DESC) END AS rn "
               "FROM memories WHERE graphed<?) WHERE rn<=?")
        return sql, [*full, below, cap]

    def list_ungraphed(self, limit: int = 40, below: int = 2,
                       cap: int = 0, full: tuple = ()) -> list[Memory]:
        if cap and cap > 0:
            sub, args = self._cap_cte(below, cap, full)
            rows = self._conn.execute(
                f"{sub} ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE graphed<? ORDER BY created_at DESC LIMIT ?",
                (below, limit)).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count_ungraphed(self, below: int = 2, cap: int = 0, full: tuple = ()) -> int:
        if cap and cap > 0:
            sub, args = self._cap_cte(below, cap, full)
            return self._conn.execute(f"SELECT COUNT(*) AS c FROM ({sub})", args).fetchone()["c"]
        return self._conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE graphed<?", (below,)).fetchone()["c"]

    def mark_graphed(self, ids: list[str], level: int = 1) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE memories SET graphed=? WHERE id=? AND graphed<?",
                [(level, i, level) for i in ids])
            self._conn.commit()

    def reset_graphed(self) -> None:
        """Mark everything as needing (re)graphing — used before a full rebuild."""
        with self._lock:
            self._conn.execute("UPDATE memories SET graphed=0")
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT source, COUNT(*) AS c FROM memories GROUP BY source"
        ).fetchall()
        return {
            "total": self.count(),
            "by_source": {r["source"]: r["c"] for r in rows},
            "embedder": self._embedder.name,
            "home": str(get_settings().home),
        }

    # ── vector cache ─────────────────────────────────────────────────────
    def _ensure_vectors(self) -> None:
        if not self._dirty and self._vecs is not None:
            return
        rows = self._conn.execute(
            "SELECT id, embedding, embed_dim FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        self._ids = []
        mats: list[np.ndarray] = []
        target_dim = self._embedder.dim
        for r in rows:
            dim = r["embed_dim"]
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            if dim != target_dim:
                # stored with a different embedder; skip from vector recall but
                # it still turns up via lexical fallback.
                continue
            self._ids.append(r["id"])
            mats.append(v)
        self._vecs = np.vstack(mats) if mats else None
        self._dirty = False

    # ── recall ───────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        source: str | None = None,
        prefer: list[str] | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        min_score: float = 0.0,
    ) -> list[RecallHit]:
        """Semantic recall with a lexical safety net, the way it gets injected.

        `prefer` softly boosts memories from those sources (e.g. the Inbox agent
        prefers 'gmail') so a domain agent's own data isn't drowned out by a
        larger source.
        """
        query = (query or "").strip()
        if not query or self.count() == 0:
            return []
        self._ensure_vectors()
        prefer = set(prefer or [])

        # date filter: restrict to memories whose real event_date is in range
        date_ids: set[str] | None = None
        if date_start or date_end:
            rows = self._conn.execute(
                "SELECT id FROM memories WHERE event_date IS NOT NULL "
                "AND event_date>=? AND event_date<=?",
                (date_start or "0000-01-01", date_end or "9999-12-31"),
            ).fetchall()
            date_ids = {r["id"] for r in rows}

        scores: dict[str, float] = {}
        if self._vecs is not None:
            qv = self._embedder.embed_query(query)
            sims = self._vecs @ qv  # cosine, vectors are normalized
            for idx, mid in enumerate(self._ids):
                scores[mid] = float(sims[idx])

        # lexical overlap boost (+ source preference) in one scan
        q_tokens = {t for t in _tokenize(query)}
        for row in self._conn.execute(
            "SELECT id, text, title, source FROM memories"
        ).fetchall():
            if q_tokens:
                toks = set(_tokenize(f"{row['title'] or ''} {row['text']}"))
                overlap = len(q_tokens & toks) / len(q_tokens) if toks else 0
                if overlap:
                    scores[row["id"]] = scores.get(row["id"], 0.0) + 0.25 * overlap
            if prefer and row["source"] in prefer and row["id"] in scores:
                scores[row["id"]] += 0.15   # soft nudge toward the agent's domain

        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        hits: list[RecallHit] = []
        for mid, score in ranked:
            if score < min_score:
                continue
            if date_ids is not None and mid not in date_ids:
                continue
            mem = self.get(mid)
            if mem is None:
                continue
            if source and mem.source != source:
                continue
            hits.append(RecallHit(memory=mem, score=round(score, 4)))
            if len(hits) >= limit:
                break
        return hits

    # ── re-embedding ──────────────────────────────────────────────────────
    def reembed_all(self, batch: int = 128) -> int:
        """Recompute every memory's vector with the current embedder. Needed
        after switching embedding providers (dimensions/model change)."""
        rows = self._conn.execute("SELECT id, text FROM memories").fetchall()
        n = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            vecs = self._embedder.embed([r["text"] for r in chunk])
            with self._lock:
                for r, v in zip(chunk, vecs):
                    self._conn.execute(
                        "UPDATE memories SET embedding=?, embed_dim=?, embed_model=? "
                        "WHERE id=?",
                        (v.tobytes(), len(v), self._embedder.name, r["id"]),
                    )
                self._conn.commit()
            n += len(chunk)
        self._dirty = True
        return n

    def dedupe(self) -> int:
        """Self-heal: remove duplicate memories of the same sourced item
        (same source+uri+title), keeping the newest. Runs automatically so no
        user ever needs a manual dedup. Only touches rows with a uri, so
        user-entered notes are never merged."""
        from collections import defaultdict
        rows = self._conn.execute(
            "SELECT id, source, uri, title, created_at FROM memories "
            "WHERE uri IS NOT NULL"
        ).fetchall()
        groups: dict = defaultdict(list)
        for r in rows:
            groups[(r["source"], r["uri"], r["title"])].append(
                (r["created_at"], r["id"]))
        to_delete = []
        for lst in groups.values():
            if len(lst) > 1:
                lst.sort()                       # oldest first
                to_delete += [i for _, i in lst[:-1]]   # keep newest
        if to_delete:
            with self._lock:
                self._conn.executemany(
                    "DELETE FROM memories WHERE id=?", [(i,) for i in to_delete])
                self._conn.commit()
                self._dirty = True
        return len(to_delete)

    # ── meta (migration version stamps) ──────────────────────────────────
    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._conn.commit()

    def embedder_signature(self) -> str:
        e = self._embedder
        return f"{e.name}:{getattr(e, 'model_name', '')}:{e.dim}"

    # ── connector state ───────────────────────────────────────────────────
    def set_connector_state(
        self, connector: str, *, cursor=None, status=None, detail=None, last_sync=None
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO connector_state (connector, cursor, last_sync, status, detail)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(connector) DO UPDATE SET
                     cursor=COALESCE(excluded.cursor, connector_state.cursor),
                     last_sync=COALESCE(excluded.last_sync, connector_state.last_sync),
                     status=excluded.status, detail=excluded.detail""",
                (connector, cursor, last_sync, status, detail),
            )
            self._conn.commit()

    def get_connector_state(self, connector: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM connector_state WHERE connector=?", (connector,)
        ).fetchone()
        return dict(row) if row else None

    def all_connector_state(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT * FROM connector_state").fetchall()
        return {r["connector"]: dict(r) for r in rows}


import re as _re

_TOKEN = _re.compile(r"[a-z0-9]{2,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are", "was",
    "what", "which", "who", "how", "when", "where", "about", "from", "have",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@lru_cache
def get_store() -> MemoryStore:
    return MemoryStore()
