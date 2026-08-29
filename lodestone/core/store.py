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
            metadata=metadata or {},
        )
        chash = _content_hash(text, uri)
        vec = self._embedder.embed_one(text)
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO memories
                       (id, text, source, kind, title, uri, tags, metadata,
                        created_at, updated_at, embedding, embed_dim, embed_model,
                        content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mem.id, mem.text, mem.source, mem.kind, mem.title, mem.uri,
                        json.dumps(mem.tags), json.dumps(mem.metadata),
                        mem.created_at, mem.updated_at,
                        vec.tobytes(), len(vec), self._embedder.name, chash,
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

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]

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
        min_score: float = 0.0,
    ) -> list[RecallHit]:
        """Semantic recall with a lexical safety net, the way it gets injected."""
        query = (query or "").strip()
        if not query or self.count() == 0:
            return []
        self._ensure_vectors()

        scores: dict[str, float] = {}
        if self._vecs is not None:
            qv = self._embedder.embed_one(query)
            sims = self._vecs @ qv  # cosine, vectors are normalized
            for idx, mid in enumerate(self._ids):
                scores[mid] = float(sims[idx])

        # lexical overlap boost — catches exact keywords the vector may miss
        q_tokens = {t for t in _tokenize(query)}
        if q_tokens:
            for row in self._conn.execute(
                "SELECT id, text, title FROM memories"
            ).fetchall():
                toks = set(_tokenize(f"{row['title'] or ''} {row['text']}"))
                if not toks:
                    continue
                overlap = len(q_tokens & toks) / len(q_tokens)
                if overlap:
                    scores[row["id"]] = scores.get(row["id"], 0.0) + 0.25 * overlap

        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        hits: list[RecallHit] = []
        for mid, score in ranked:
            if score < min_score:
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
