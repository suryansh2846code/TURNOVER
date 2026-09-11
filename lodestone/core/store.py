"""The memory store: the local 'brain' — Brain v1.5.

Persists memories to SQLite with their embeddings and provides semantic +
lexical recall over them. Vectors are stored as float32 blobs and searched with
NumPy. In Brain v1.5, memories are upgraded with temporal metadata, confidence,
importance, reinforcement, lifecycle status, provenance, and open loops.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..config import get_settings
from .db import connect
from .embeddings import get_embedder
from .models import (
    Memory,
    MemoryStatus,
    MemoryType,
    OpenLoop,
    OpenLoopPriority,
    OpenLoopStatus,
    RecallExplanation,
    RecallHit,
    map_kind_to_memory_type,
)

log = logging.getLogger("lodestone.store")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(text: str, uri: str | None) -> str:
    h = hashlib.sha256()
    h.update((uri or "").encode())
    h.update(b"\x00")
    h.update(text.strip().encode())
    return h.hexdigest()


def _safe_json_loads(val: Any, default: Any) -> Any:
    if not val:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def _row_to_memory(row: sqlite3.Row) -> Memory:
    keys = row.keys()
    m_type = row["memory_type"] if "memory_type" in keys else None
    if not m_type and "kind" in keys and row["kind"]:
        k = row["kind"]
        m_type = k if k in MemoryType._value2member_map_ else "semantic"

    return Memory(
        id=row["id"],
        text=row["text"],
        source=row["source"],
        kind=row["kind"],
        title=row["title"],
        uri=row["uri"],
        memory_type=m_type or "semantic",
        source_id=row["source_id"] if "source_id" in keys else None,
        extraction_method=row["extraction_method"] if "extraction_method" in keys and row["extraction_method"] else "direct",
        evidence=row["evidence"] if "evidence" in keys else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        event_date=row["event_date"] if "event_date" in keys else None,
        event_time=row["event_time"] if "event_time" in keys else None,
        valid_from=row["valid_from"] if "valid_from" in keys else None,
        valid_until=row["valid_until"] if "valid_until" in keys else None,
        importance=float(row["importance"]) if "importance" in keys and row["importance"] is not None else 0.5,
        confidence=float(row["confidence"]) if "confidence" in keys and row["confidence"] is not None else 0.8,
        reinforcement_count=int(row["reinforcement_count"]) if "reinforcement_count" in keys and row["reinforcement_count"] is not None else 0,
        last_reinforced_at=row["last_reinforced_at"] if "last_reinforced_at" in keys else None,
        last_accessed_at=row["last_accessed_at"] if "last_accessed_at" in keys else None,
        access_count=int(row["access_count"]) if "access_count" in keys and row["access_count"] is not None else 0,
        status=row["status"] if "status" in keys and row["status"] else "active",
        supersedes_id=row["supersedes_id"] if "supersedes_id" in keys else None,
        tags=_safe_json_loads(row["tags"] if "tags" in keys else None, []),
        metadata=_safe_json_loads(row["metadata"] if "metadata" in keys else None, {}),
    )


def _row_to_open_loop(row: sqlite3.Row) -> OpenLoop:
    return OpenLoop(
        id=row["id"],
        description=row["description"],
        status=row["status"],
        priority=row["priority"],
        confidence=float(row["confidence"]),
        due_at=row["due_at"],
        source=row["source"],
        related_entities=_safe_json_loads(row["related_entities"], []),
        related_project=row["related_project"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        metadata=_safe_json_loads(row["metadata"], {}),
    )


_HISTORICAL_WORDS = re.compile(
    r"\b(previously|used to|past|formerly|before|history|historical|earlier|was|old|prior|back then|"
    r"in 20\d\d)\b", re.I
)


class MemoryStore:
    def __init__(self, db_path=None, embedder=None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.db_path
        self._conn = connect(self.db_path)
        self._lock = threading.Lock()
        self._embedder = embedder or get_embedder()
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
        # Brain v1.5 fields
        memory_type: str | None = None,
        source_id: str | None = None,
        event_time: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        reinforcement_count: int = 0,
        last_reinforced_at: str | None = None,
        status: str = "active",
        extraction_method: str = "direct",
        supersedes_id: str | None = None,
        evidence: str | None = None,
    ) -> Memory | None:
        """Add one memory with Brain v1.5 metadata. Returns None if duplicate."""
        raw_text = (text or "").strip()
        if not raw_text:
            return None

        # Secret protection: drop blatant credential resets, redact inline secrets
        from ..brain.canonical.redact import is_sensitive, redact
        if is_sensitive(raw_text):
            return None
        safe_text = redact(raw_text)

        # Map kind to memory type if not explicitly supplied
        m_type = memory_type or map_kind_to_memory_type(kind)

        # Default importance based on source & type
        if importance is None:
            if m_type == MemoryType.PREFERENCE.value or source in ("chat", "manual"):
                importance = 0.8
            elif m_type == MemoryType.COMMITMENT.value:
                importance = 0.85
            else:
                importance = 0.5

        # Default confidence based on source & extraction method
        if confidence is None:
            if extraction_method == "user_statement" or source in ("chat", "manual"):
                confidence = 0.95
            elif source in ("gmail", "apple_mail", "linear", "github", "notion"):
                confidence = 0.85
            elif extraction_method == "llm_inference":
                confidence = 0.70
            elif extraction_method == "heuristic":
                confidence = 0.50
            else:
                confidence = 0.80

        # Inherit event_date from valid_from or event_time if missing
        if not event_date:
            if event_time:
                event_date = event_time[:10]
            elif valid_from:
                event_date = valid_from[:10]

        now_str = _now()
        mem = Memory(
            id=str(uuid.uuid4()),
            text=safe_text,
            source=source,
            kind=kind,
            title=title,
            uri=uri,
            memory_type=m_type,
            source_id=source_id,
            extraction_method=extraction_method,
            evidence=evidence,
            created_at=now_str,
            updated_at=now_str,
            event_date=event_date,
            event_time=event_time,
            valid_from=valid_from or (event_date if event_date else now_str[:10]),
            valid_until=valid_until,
            importance=float(importance),
            confidence=float(confidence),
            reinforcement_count=reinforcement_count,
            last_reinforced_at=last_reinforced_at,
            status=status,
            supersedes_id=supersedes_id,
            tags=list(tags or []),
            metadata=metadata or {},
        )

        chash = _content_hash(safe_text, uri)
        # Skip if we already have this exact content hash
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM memories WHERE content_hash=?", (chash,)
            ).fetchone()
            if existing:
                return None

        vec = self._embedder.embed_one(safe_text)
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO memories
                       (id, text, source, kind, title, uri, tags, metadata,
                        created_at, updated_at, embedding, embed_dim, embed_model,
                        content_hash, event_date, graphed,
                        memory_type, source_id, event_time, valid_from, valid_until,
                        importance, confidence, reinforcement_count, last_reinforced_at,
                        last_accessed_at, access_count, status, extraction_method,
                        supersedes_id, evidence)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,NULL,0,?,?,?,?)""",
                    (
                        mem.id, mem.text, mem.source, mem.kind, mem.title, mem.uri,
                        json.dumps(mem.tags), json.dumps(mem.metadata),
                        mem.created_at, mem.updated_at,
                        vec.tobytes(), len(vec), self._embedder.name, chash,
                        mem.event_date,
                        mem.memory_type, mem.source_id, mem.event_time, mem.valid_from,
                        mem.valid_until, mem.importance, mem.confidence,
                        mem.reinforcement_count, mem.last_reinforced_at,
                        mem.status, mem.extraction_method, mem.supersedes_id,
                        mem.evidence,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return None  # duplicate content_hash race
            self._dirty = True
        return mem

    def add_many(self, items: list[dict[str, Any]]) -> int:
        added = 0
        for item in items:
            if self.add(**item):
                added += 1
        return added

    def update(self, memory_id: str, **fields: Any) -> Memory | None:
        """Update specific fields of an existing memory."""
        mem = self.get(memory_id)
        if not mem:
            return None
        now_str = _now()
        allowed = {
            "text", "title", "status", "valid_from", "valid_until", "importance",
            "confidence", "reinforcement_count", "last_reinforced_at", "tags",
            "metadata", "supersedes_id", "memory_type", "evidence"
        }
        updates = {}
        for k, v in fields.items():
            if k in allowed:
                updates[k] = v
        if not updates:
            return mem

        with self._lock:
            set_clauses = []
            params = []
            re_embed = False
            for k, v in updates.items():
                if k in ("tags", "metadata"):
                    set_clauses.append(f"{k} = ?")
                    params.append(json.dumps(v))
                else:
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                if k == "text":
                    re_embed = True

            set_clauses.append("updated_at = ?")
            params.append(now_str)

            if re_embed:
                vec = self._embedder.embed_one(updates["text"])
                set_clauses.append("embedding = ?")
                params.append(vec.tobytes())
                set_clauses.append("embed_dim = ?")
                params.append(len(vec))
                set_clauses.append("content_hash = ?")
                params.append(_content_hash(updates["text"], mem.uri))
                self._dirty = True

            params.append(memory_id)
            sql = f"UPDATE memories SET {', '.join(set_clauses)} WHERE id = ?"
            self._conn.execute(sql, params)
            self._conn.commit()

        return self.get(memory_id)

    def reinforce(self, memory_id: str, count: int = 1) -> bool:
        """Meaningfully reinforce a memory after repeated confirmation."""
        now_str = _now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET reinforcement_count = reinforcement_count + ?, "
                "last_reinforced_at = ?, confidence = MIN(1.0, confidence + 0.05), "
                "updated_at = ? WHERE id = ?",
                (count, now_str, now_str, memory_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def update_status(self, memory_id: str, status: str, valid_until: str | None = None) -> bool:
        """Change status (active, superseded, uncertain, disputed, expired, retracted)."""
        now_str = _now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET status = ?, valid_until = COALESCE(?, valid_until), "
                "updated_at = ? WHERE id = ?",
                (status, valid_until, now_str, memory_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def supersede(self, old_memory_id: str, new_memory_id: str, valid_until: str | None = None) -> bool:
        """Mark old_memory as superseded by new_memory without destroying history."""
        now_str = _now()
        vu = valid_until or now_str[:10]
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET status = 'superseded', valid_until = ?, updated_at = ? WHERE id = ?",
                (vu, now_str, old_memory_id),
            )
            self._conn.execute(
                "UPDATE memories SET supersedes_id = ?, updated_at = ? WHERE id = ?",
                (old_memory_id, now_str, new_memory_id),
            )
            self._conn.commit()
            return True

    def record_access(self, memory_ids: list[str]) -> None:
        """Track memory access on recall hits without blocking callers."""
        if not memory_ids:
            return
        now_str = _now()
        with self._lock:
            self._conn.executemany(
                "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                [(now_str, mid) for mid in memory_ids],
            )
            self._conn.commit()

    def delete(self, memory_id: str, soft: bool = False) -> bool:
        """Delete a memory. If soft=True, sets status='retracted' to preserve provenance."""
        if soft:
            return self.update_status(memory_id, MemoryStatus.RETRACTED.value)
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
        self,
        *,
        source: str | None = None,
        status: str | None = None,
        memory_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        clauses = []
        params: list[Any] = []
        if source:
            clauses.append("source=?")
            params.append(source)
        if status:
            clauses.append("status=?")
            params.append(status)
        if memory_type:
            clauses.append("memory_type=?")
            params.append(memory_type)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM memories {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def export_all(self) -> list[dict[str, Any]]:
        """Every memory as a portable dict (no vectors — re-embedded on import)."""
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
                    "memory_type": m.memory_type, "source_id": m.source_id,
                    "event_time": m.event_time, "valid_from": m.valid_from,
                    "valid_until": m.valid_until, "importance": m.importance,
                    "confidence": m.confidence, "reinforcement_count": m.reinforcement_count,
                    "status": m.status, "extraction_method": m.extraction_method,
                    "evidence": m.evidence, "supersedes_id": m.supersedes_id,
                })
            offset += len(rows)
        return out

    def count(self, status: str | None = None) -> int:
        if status:
            return self._conn.execute("SELECT COUNT(*) AS c FROM memories WHERE status=?", (status,)).fetchone()["c"]
        return self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]

    # ── knowledge-graph enrichment queue ─────────────────────────────────
    def _cap_cte(self, below: int, cap: int, full: tuple) -> tuple[str, list]:
        ph = ",".join("?" for _ in full) or "''"
        sql = (f"SELECT * FROM (SELECT *, CASE WHEN source IN ({ph}) THEN 0 ELSE "
               "ROW_NUMBER() OVER (PARTITION BY source ORDER BY created_at DESC) END AS rn "
               "FROM memories WHERE graphed<? AND status != 'retracted') WHERE rn<=?")
        return sql, [*full, below, cap]

    def list_ungraphed(self, limit: int = 40, below: int = 2,
                       cap: int = 0, full: tuple = ()) -> list[Memory]:
        if cap and cap > 0:
            sub, args = self._cap_cte(below, cap, full)
            rows = self._conn.execute(
                f"{sub} ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE graphed<? AND status != 'retracted' ORDER BY created_at DESC LIMIT ?",
                (below, limit)).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count_ungraphed(self, below: int = 2, cap: int = 0, full: tuple = ()) -> int:
        if cap and cap > 0:
            sub, args = self._cap_cte(below, cap, full)
            return self._conn.execute(f"SELECT COUNT(*) AS c FROM ({sub})", args).fetchone()["c"]
        return self._conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE graphed<? AND status != 'retracted'", (below,)).fetchone()["c"]

    def mark_graphed(self, ids: list[str], level: int = 1) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE memories SET graphed=? WHERE id=? AND graphed<?",
                [(level, i, level) for i in ids])
            self._conn.commit()

    def reset_graphed(self) -> None:
        with self._lock:
            self._conn.execute("UPDATE memories SET graphed=0")
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT source, COUNT(*) AS c FROM memories GROUP BY source"
        ).fetchall()
        status_rows = self._conn.execute(
            "SELECT status, COUNT(*) AS c FROM memories GROUP BY status"
        ).fetchall()
        type_rows = self._conn.execute(
            "SELECT memory_type, COUNT(*) AS c FROM memories GROUP BY memory_type"
        ).fetchall()
        loop_rows = self._conn.execute(
            "SELECT status, COUNT(*) AS c FROM open_loops GROUP BY status"
        ).fetchall()
        return {
            "total": self.count(),
            "by_source": {r["source"]: r["c"] for r in rows},
            "by_status": {r["status"]: r["c"] for r in status_rows},
            "by_type": {r["memory_type"]: r["c"] for r in type_rows},
            "open_loops": {r["status"]: r["c"] for r in loop_rows},
            "embedder": self._embedder.name,
            "home": str(get_settings().home),
        }

    # ── vector cache ─────────────────────────────────────────────────────
    def _ensure_vectors(self) -> None:
        if not self._dirty and self._vecs is not None:
            return
        rows = self._conn.execute(
            "SELECT id, embedding, embed_dim FROM memories "
            "WHERE embedding IS NOT NULL AND status != 'retracted'"
        ).fetchall()
        self._ids = []
        mats: list[np.ndarray] = []
        target_dim = self._embedder.dim
        for r in rows:
            dim = r["embed_dim"]
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            if dim != target_dim:
                continue
            self._ids.append(r["id"])
            mats.append(v)
        self._vecs = np.vstack(mats) if mats else None
        self._dirty = False

    # ── recall / search ───────────────────────────────────────────────────
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
        include_superseded: bool | None = None,
    ) -> list[RecallHit]:
        """Hybrid multi-signal recall engine for Brain v1.5 with explainability.

        Formula:
          score = semantic_sim
                + lexical_relevance
                + importance_boost
                + confidence_boost
                + recency_boost
                + temporal_match_boost
                + reinforcement_boost
                + source_boost
                - status_penalty
        """
        query = (query or "").strip()
        if not query or self.count() == 0:
            return []
        self._ensure_vectors()
        prefer_set = set(prefer or [])

        # Check if user query explicitly asks for historical context
        historical_query = bool(_HISTORICAL_WORDS.search(query))
        if include_superseded is None:
            include_superseded = historical_query

        # Date filter restriction
        date_ids: set[str] | None = None
        if date_start or date_end:
            rows = self._conn.execute(
                "SELECT id FROM memories WHERE event_date IS NOT NULL "
                "AND event_date>=? AND event_date<=?",
                (date_start or "0000-01-01", date_end or "9999-12-31"),
            ).fetchall()
            date_ids = {r["id"] for r in rows}

        # 1. Semantic similarities
        raw_sims: dict[str, float] = {}
        if self._vecs is not None:
            try:
                qv = self._embedder.embed_query(query)
                sims = self._vecs @ qv  # cosine similarity
                for idx, mid in enumerate(self._ids):
                    raw_sims[mid] = float(sims[idx])
            except Exception:
                raw_sims = {}

        # 2. Tokenize query for lexical relevance
        q_tokens = set(_tokenize(query))

        # Fetch candidate memory metadata in one batch
        cand_rows = self._conn.execute(
            "SELECT id, text, title, source, memory_type, event_date, valid_from, valid_until, "
            "importance, confidence, reinforcement_count, status, created_at, updated_at "
            "FROM memories WHERE status != 'retracted'"
        ).fetchall()

        now_dt = datetime.now(timezone.utc)
        scored_hits: list[RecallHit] = []

        for row in cand_rows:
            mid = row["id"]
            m_status = row["status"]

            # Filter out non-historical superseded rows unless requested
            if m_status == "superseded" and not include_superseded:
                continue

            factors = []
            sem_score = raw_sims.get(mid, 0.0)
            if sem_score > 0.1:
                factors.append(f"semantic_similarity:{round(sem_score, 3)}")

            # Lexical overlap
            lex_score = 0.0
            if q_tokens:
                target_text = f"{row['title'] or ''} {row['text']}"
                t_tokens = set(_tokenize(target_text))
                if t_tokens:
                    overlap = len(q_tokens & t_tokens) / len(q_tokens)
                    lex_score = 0.30 * overlap
                    if overlap > 0.0:
                        factors.append(f"lexical_overlap:{round(overlap, 2)}")

            # Base combined retrieval score
            score = sem_score + lex_score

            # Importance boost (0.0 to 0.15)
            imp = float(row["importance"]) if row["importance"] is not None else 0.5
            imp_boost = 0.15 * imp
            if imp >= 0.7:
                factors.append(f"high_importance:{round(imp, 2)}")

            # Confidence boost (-0.05 to +0.07)
            conf = float(row["confidence"]) if row["confidence"] is not None else 0.8
            conf_boost = 0.10 * (conf - 0.5)

            # Reinforcement boost
            r_count = int(row["reinforcement_count"]) if row["reinforcement_count"] is not None else 0
            reinf_boost = min(0.12, r_count * 0.03)
            if r_count > 0:
                factors.append(f"reinforced:{r_count}x")

            # Source quality & preference boost
            src = row["source"]
            src_boost = 0.0
            if src in ("chat", "manual"):
                src_boost += 0.08
            elif src in ("linear", "github", "notion", "gdrive", "files"):
                src_boost += 0.05
            elif src in ("gmail", "apple_mail", "imessage"):
                src_boost += 0.04

            if src in prefer_set:
                src_boost += 0.15
                factors.append(f"preferred_source:{src}")

            # Recency boost
            recency_boost = 0.0
            date_str = row["event_date"] or row["created_at"]
            try:
                d_then = datetime.fromisoformat(date_str.replace("Z", "+00:00")[:10])
                days_ago = max(0.0, (now_dt.date() - d_then.date()).days)
                recency_boost = 0.08 * math.exp(-days_ago / 90.0)
            except Exception:
                recency_boost = 0.02

            # Temporal match boost
            temporal_boost = 0.0
            v_from = row["valid_from"]
            v_until = row["valid_until"]
            if date_ids is not None and mid in date_ids:
                temporal_boost += 0.25
                factors.append("date_filter_match")

            if historical_query:
                if m_status == "superseded" or v_until is not None:
                    temporal_boost += 0.20
                    factors.append("historical_match")
            else:
                # Query is about present
                if m_status == "active" and v_until is None:
                    temporal_boost += 0.05

            # Penalties
            penalties = 0.0
            if m_status == "superseded":
                if not historical_query:
                    penalties += 0.40
                    factors.append("superseded_penalty")
            elif m_status in ("uncertain", "disputed"):
                penalties += 0.15
                factors.append("uncertain_penalty")

            total_score = (
                score
                + imp_boost
                + conf_boost
                + reinf_boost
                + src_boost
                + recency_boost
                + temporal_boost
                - penalties
            )

            if total_score < min_score:
                continue
            if date_ids is not None and mid not in date_ids:
                continue
            if source and src != source:
                continue

            explanation = RecallExplanation(
                semantic_similarity=round(sem_score, 4),
                lexical_relevance=round(lex_score, 4),
                importance_boost=round(imp_boost, 4),
                confidence_boost=round(conf_boost, 4),
                recency_boost=round(recency_boost, 4),
                temporal_boost=round(temporal_boost, 4),
                reinforcement_boost=round(reinf_boost, 4),
                source_boost=round(src_boost, 4),
                penalties=round(penalties, 4),
                total_score=round(total_score, 4),
                factors=factors,
            )

            # Lazy-load full Memory object only for qualifying candidates
            mem = self.get(mid)
            if mem:
                scored_hits.append(RecallHit(memory=mem, score=round(total_score, 4), explanation=explanation))

        scored_hits.sort(key=lambda h: h.score, reverse=True)
        final_hits = scored_hits[:limit]

        # Record access frequency and timestamp for returned memories
        if final_hits:
            self.record_access([h.memory.id for h in final_hits])

        return final_hits

    # ── open loops ────────────────────────────────────────────────────────
    def add_open_loop(
        self,
        description: str,
        *,
        status: str = "open",
        priority: str = "medium",
        confidence: float = 0.8,
        due_at: str | None = None,
        source: str = "manual",
        related_entities: list[str] | None = None,
        related_project: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OpenLoop | None:
        """Create an open loop (commitment, follow-up, pending decision)."""
        desc = (description or "").strip()
        if not desc:
            return None
        loop = OpenLoop(
            id=str(uuid.uuid4()),
            description=desc,
            status=status,
            priority=priority,
            confidence=confidence,
            due_at=due_at,
            source=source,
            related_entities=list(related_entities or []),
            related_project=related_project,
            created_at=_now(),
            updated_at=_now(),
            metadata=metadata or {},
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO open_loops
                   (id, description, status, priority, confidence, due_at, source,
                    related_entities, related_project, created_at, updated_at, completed_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
                (
                    loop.id, loop.description, loop.status, loop.priority,
                    loop.confidence, loop.due_at, loop.source,
                    json.dumps(loop.related_entities), loop.related_project,
                    loop.created_at, loop.updated_at, json.dumps(loop.metadata),
                ),
            )
            self._conn.commit()
        return loop

    def get_open_loop(self, loop_id: str) -> OpenLoop | None:
        row = self._conn.execute("SELECT * FROM open_loops WHERE id=?", (loop_id,)).fetchone()
        return _row_to_open_loop(row) if row else None

    def update_open_loop(self, loop_id: str, **fields: Any) -> OpenLoop | None:
        loop = self.get_open_loop(loop_id)
        if not loop:
            return None
        now_str = _now()
        allowed = {"description", "status", "priority", "confidence", "due_at",
                   "related_entities", "related_project", "metadata"}
        clauses = []
        params: list[Any] = []
        for k, v in fields.items():
            if k in allowed:
                if k in ("related_entities", "metadata"):
                    clauses.append(f"{k} = ?")
                    params.append(json.dumps(v))
                else:
                    clauses.append(f"{k} = ?")
                    params.append(v)
        if not clauses:
            return loop

        if fields.get("status") in ("completed", "cancelled") and not loop.completed_at:
            clauses.append("completed_at = ?")
            params.append(now_str)

        clauses.append("updated_at = ?")
        params.append(now_str)
        params.append(loop_id)

        sql = f"UPDATE open_loops SET {', '.join(clauses)} WHERE id = ?"
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()
        return self.get_open_loop(loop_id)

    def complete_open_loop(self, loop_id: str) -> OpenLoop | None:
        return self.update_open_loop(loop_id, status=OpenLoopStatus.COMPLETED.value)

    def list_open_loops(
        self,
        *,
        status: str | None = None,
        related_project: str | None = None,
        limit: int = 50,
    ) -> list[OpenLoop]:
        clauses = []
        params: list[Any] = []
        if status == "active":
            clauses.append("status IN ('open', 'waiting', 'blocked')")
        elif status:
            clauses.append("status=?")
            params.append(status)
        if related_project:
            clauses.append("related_project=?")
            params.append(related_project)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM open_loops {where} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_open_loop(r) for r in rows]

    # ── re-embedding ──────────────────────────────────────────────────────
    def reembed_all(self, batch: int = 128) -> int:
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
        (same source+uri+title), keeping the newest or highest-reinforced."""
        rows = self._conn.execute(
            "SELECT id, source, uri, title, created_at, reinforcement_count FROM memories "
            "WHERE uri IS NOT NULL"
        ).fetchall()
        groups: dict = defaultdict(list)
        for r in rows:
            groups[(r["source"], r["uri"], r["title"])].append(
                (r["created_at"], r["reinforcement_count"], r["id"]))
        to_delete = []
        for lst in groups.values():
            if len(lst) > 1:
                # Sort by reinforcement count, then created_at
                lst.sort(key=lambda x: (x[1], x[0]))
                to_delete += [i for _, _, i in lst[:-1]]  # keep highest / newest
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


_TOKEN = re.compile(r"[a-z0-9]{2,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are", "was",
    "what", "which", "who", "how", "when", "where", "about", "from", "have",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@lru_cache
def get_store() -> MemoryStore:
    return MemoryStore()
