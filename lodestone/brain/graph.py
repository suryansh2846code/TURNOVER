"""Knowledge-graph operations over the shared SQLite connection."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import numpy as np

from ..core.embeddings import get_embedder


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


class GraphStore:
    """Entities + relations, sharing MemoryStore's connection and lock."""

    def __init__(self, store) -> None:
        self._store = store
        self._conn = store._conn
        self._lock = store._lock
        self._embedder = get_embedder()

    # ── entities ─────────────────────────────────────────────────────────
    def upsert_entity(self, name: str, *, type: str = "thing",
                      summary: str = "") -> str:
        norm = _norm(name)
        if not norm:
            return ""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, summary FROM entities WHERE norm=?", (norm,)
            ).fetchone()
            if row:
                new_summary = summary or row["summary"]
                self._conn.execute(
                    "UPDATE entities SET mentions=mentions+1, updated_at=?, "
                    "summary=?, type=COALESCE(NULLIF(type,'thing'), type) "
                    "WHERE id=?",
                    (_now(), new_summary, row["id"]),
                )
                self._conn.commit()
                return row["id"]
            eid = str(uuid.uuid4())
            vec = self._embedder.embed_one(f"{name}. {summary}")
            self._conn.execute(
                "INSERT INTO entities (id,name,norm,type,summary,mentions,"
                "embedding,embed_dim,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
                (eid, name.strip(), norm, type, summary, vec.tobytes(),
                 len(vec), _now(), _now()),
            )
            self._conn.commit()
            return eid

    def add_relation(self, subject_id: str, predicate: str,
                     object_id: str | None, fact: str,
                     source_mem: str | None = None) -> None:
        if not subject_id or not fact.strip():
            return
        with self._lock:
            # avoid exact-duplicate facts
            dup = self._conn.execute(
                "SELECT 1 FROM relations WHERE subject_id=? AND fact=?",
                (subject_id, fact),
            ).fetchone()
            if dup:
                return
            self._conn.execute(
                "INSERT INTO relations (id,subject_id,predicate,object_id,fact,"
                "source_mem,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), subject_id, predicate, object_id, fact,
                 source_mem, _now()),
            )
            self._conn.commit()

    # ── query ────────────────────────────────────────────────────────────
    def match_entities(self, query: str, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id,name,type,summary,mentions,embedding,embed_dim FROM entities"
        ).fetchall()
        if not rows:
            return []
        qv = self._embedder.embed_one(query)
        scored = []
        ql = query.lower()
        for r in rows:
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            score = float(v @ qv) if len(v) == len(qv) else 0.0
            if r["name"].lower() in ql or _norm(r["name"]) in ql:
                score += 0.5
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": r["id"], "name": r["name"], "type": r["type"],
             "summary": r["summary"], "mentions": r["mentions"], "score": round(s, 3)}
            for s, r in scored[:limit] if s > 0.05
        ]

    def facts_for(self, entity_id: str, limit: int = 8) -> list[str]:
        rows = self._conn.execute(
            "SELECT fact FROM relations WHERE subject_id=? OR object_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (entity_id, entity_id, limit),
        ).fetchall()
        return [r["fact"] for r in rows]

    def stats(self) -> dict:
        e = self._conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
        r = self._conn.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"]
        types = self._conn.execute(
            "SELECT type, COUNT(*) c FROM entities GROUP BY type"
        ).fetchall()
        return {"entities": e, "relations": r,
                "by_type": {t["type"]: t["c"] for t in types}}

    def top_entities(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id,name,type,summary,mentions FROM entities "
            "ORDER BY mentions DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
