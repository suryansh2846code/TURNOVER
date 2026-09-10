"""Knowledge-graph operations over the shared SQLite connection — Brain v1.5."""
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
    return re.sub(r"\s+", " ", (name or "").strip().lower())


# Canonical supported entity types
ENTITY_TYPES = {
    "person", "organization", "project", "place", "product",
    "technology", "concept", "event", "thing", "tool", "topic"
}


class GraphStore:
    """Entities + relations in Brain v1.5 with aliases, provenance, confidence, and temporal bounds."""

    def __init__(self, store) -> None:
        self._store = store
        self._conn = store._conn
        self._lock = store._lock
        self._embedder = get_embedder()

    # ── entities ─────────────────────────────────────────────────────────
    def upsert_entity(
        self,
        name: str,
        *,
        type: str = "thing",
        summary: str = "",
        aliases: list[str] | None = None,
        confidence: float = 0.8,
        importance: float = 0.5,
        source: str = "direct",
    ) -> str:
        """Upsert an entity with quality filtering, aliases, and normalization."""
        from .extract import is_good_entity
        cleaned = (name or "").strip()
        if not cleaned or not is_good_entity(cleaned):
            return ""
        norm = _norm(cleaned)
        etype = type.lower() if type.lower() in ENTITY_TYPES else "thing"
        new_aliases = [_norm(a) for a in (aliases or []) if _norm(a) and _norm(a) != norm]

        with self._lock:
            # 1. Look up by direct norm
            row = self._conn.execute(
                "SELECT * FROM entities WHERE norm=?", (norm,)
            ).fetchone()

            # 2. Look up by alias if not found directly
            if not row:
                for r in self._conn.execute("SELECT * FROM entities").fetchall():
                    existing_aliases = json.loads(r["aliases"]) if "aliases" in r.keys() and r["aliases"] else []
                    if norm in existing_aliases:
                        row = r
                        break

            if row:
                existing_aliases = json.loads(row["aliases"]) if "aliases" in row.keys() and row["aliases"] else []
                merged_aliases = list(set(existing_aliases + new_aliases))
                new_summary = summary or row["summary"]
                new_type = row["type"] if row["type"] != "thing" else etype
                new_imp = min(1.0, (row["importance"] if "importance" in row.keys() else 0.5) + 0.05)
                new_conf = max(float(row["confidence"] if "confidence" in row.keys() else 0.8), confidence)

                self._conn.execute(
                    """UPDATE entities SET
                       mentions = mentions + 1,
                       updated_at = ?,
                       summary = ?,
                       type = ?,
                       aliases = ?,
                       importance = ?,
                       confidence = ?
                       WHERE id = ?""",
                    (_now(), new_summary, new_type, json.dumps(merged_aliases),
                     new_imp, new_conf, row["id"]),
                )
                self._conn.commit()
                return row["id"]

            # 3. Create new entity
            eid = str(uuid.uuid4())
            vec = self._embedder.embed_one(f"{cleaned}. {summary}")
            self._conn.execute(
                """INSERT INTO entities
                   (id, name, norm, type, summary, mentions, embedding, embed_dim,
                    created_at, updated_at, aliases, confidence, importance, source)
                   VALUES (?,?,?,?,?,1,?,?,?,?,?,?,?,?)""",
                (
                    eid, cleaned, norm, etype, summary, vec.tobytes(),
                    len(vec), _now(), _now(), json.dumps(new_aliases),
                    confidence, importance, source,
                ),
            )
            self._conn.commit()
            return eid

    def get_entity(self, entity_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["aliases"] = json.loads(d["aliases"]) if "aliases" in d and d["aliases"] else []
        d.pop("embedding", None)
        return d

    def add_relation(
        self,
        subject_id: str,
        predicate: str,
        object_id: str | None,
        fact: str,
        source_mem: str | None = None,
        confidence: float = 0.8,
        source: str = "direct",
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None:
        if not subject_id or not fact.strip():
            return
        with self._lock:
            dup = self._conn.execute(
                "SELECT 1 FROM relations WHERE subject_id=? AND fact=?",
                (subject_id, fact.strip()),
            ).fetchone()
            if dup:
                return
            self._conn.execute(
                """INSERT INTO relations
                   (id, subject_id, predicate, object_id, fact, source_mem, created_at,
                    confidence, source, valid_from, valid_until)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), subject_id, predicate.strip(), object_id,
                    fact.strip(), source_mem, _now(), confidence, source,
                    valid_from, valid_until,
                ),
            )
            self._conn.commit()

    # ── query ────────────────────────────────────────────────────────────
    def match_entities(self, query: str, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, norm, type, summary, mentions, embedding, embed_dim, "
            "aliases, confidence, importance FROM entities"
        ).fetchall()
        if not rows:
            return []
        try:
            qv = self._embedder.embed_one(query)
        except Exception:
            qv = None
        scored = []
        ql = query.lower()
        for r in rows:
            if qv is not None and r["embedding"]:
                v = np.frombuffer(r["embedding"], dtype=np.float32)
                score = float(v @ qv) if len(v) == len(qv) else 0.0
            else:
                score = 0.0
            name_lower = r["name"].lower()
            if name_lower in ql or _norm(r["name"]) in ql:
                score += 0.5
            else:
                aliases = json.loads(r["aliases"]) if "aliases" in r.keys() and r["aliases"] else []
                if any(a in ql for a in aliases):
                    score += 0.4
            # Importance nudge
            imp = r["importance"] if "importance" in r.keys() and r["importance"] is not None else 0.5
            score += 0.1 * imp
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "summary": r["summary"],
                "mentions": r["mentions"],
                "confidence": r["confidence"] if "confidence" in r.keys() else 0.8,
                "importance": r["importance"] if "importance" in r.keys() else 0.5,
                "score": round(s, 3),
            }
            for s, r in scored[:limit] if s > 0.05
        ]

    def facts_for(self, entity_id: str, limit: int = 8) -> list[str]:
        rows = self._conn.execute(
            "SELECT fact, confidence, valid_until FROM relations WHERE subject_id=? OR object_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (entity_id, entity_id, limit),
        ).fetchall()
        facts = []
        for r in rows:
            tag = " [HISTORICAL]" if r["valid_until"] else ""
            facts.append(f"{r['fact']}{tag}")
        return facts

    def get_related(self, entity_id: str, limit: int = 10) -> list[dict]:
        """Return entities connected to entity_id via relations."""
        rows = self._conn.execute(
            """SELECT r.predicate, r.fact, r.confidence, r.valid_until,
                      e.id AS target_id, e.name AS target_name, e.type AS target_type
               FROM relations r
               JOIN entities e ON (e.id = CASE WHEN r.subject_id = ? THEN r.object_id ELSE r.subject_id END)
               WHERE (r.subject_id = ? OR r.object_id = ?) AND e.id != ?
               LIMIT ?""",
            (entity_id, entity_id, entity_id, entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        e = self._conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
        r = self._conn.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"]
        types = self._conn.execute(
            "SELECT type, COUNT(*) c FROM entities GROUP BY type"
        ).fetchall()
        return {"entities": e, "relations": r,
                "by_type": {t["type"]: t["c"] for t in types}}

    def prune_noise(self) -> dict:
        """Delete entities that fail the quality filter (and their relations).
        Cleans up junk like common words captured as entities."""
        from .extract import is_good_entity
        rows = self._conn.execute("SELECT id, name FROM entities").fetchall()
        bad = [r["id"] for r in rows if not is_good_entity(r["name"])]
        removed_facts = 0
        with self._lock:
            for eid in bad:
                cur = self._conn.execute(
                    "DELETE FROM relations WHERE subject_id=? OR object_id=?",
                    (eid, eid))
                removed_facts += cur.rowcount
                self._conn.execute("DELETE FROM entities WHERE id=?", (eid,))
            self._conn.commit()
        return {"removed_entities": len(bad), "removed_facts": removed_facts}

    def top_entities(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, type, summary, mentions, confidence, importance FROM entities "
            "ORDER BY mentions DESC, importance DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
