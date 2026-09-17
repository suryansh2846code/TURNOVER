"""Knowledge-graph operations over the shared SQLite connection — Brain v1.5."""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

import numpy as np

from ..core.embeddings import get_embedder


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


# Canonical supported entity types
ENTITY_TYPES = {
    "person", "organization", "project", "place", "product",
    "technology", "concept", "event", "thing", "tool", "topic"
}

#: The four areas the "Here's your brain" digest is organised into, and the
#: entity TYPES that belong to each.
#:
#: Keyed on the type the extractor derived from CONTENT — never on the connector
#: a memory arrived from. A source→area allowlist is what this replaced: it filed
#: every Notion page under "work" whether it was a project spec or a birthday
#: list, and it silently dropped any connector nobody had added to the map.
#: Content decides the area; the list of sources is derived from it afterwards.
#:
#: `thing` is deliberately unmapped. It is the extractor saying "I could not
#: tell", and spreading those over four areas is how a digest starts inventing.
DIGEST_AREAS: dict[str, tuple[str, ...]] = {
    "work": ("organization", "project", "product", "tool", "technology"),
    "learning": ("concept", "topic"),
    "comm": ("person",),
    "personal": ("place", "event"),
}



def _num(value: object, default: float) -> float:
    """A numeric column, or `default` when it is missing or NULL.

    Rows here are `sqlite3.Row`, where `"col" in row` tests the row's VALUES
    rather than its keys — so the `if "importance" in row else 0.5` guards this
    replaces were almost always False, and every entity silently kept the
    default importance and confidence no matter what had been stored. The
    columns themselves are NOT NULL with defaults and are backfilled by
    `core/db.py::_migrate`, so the only case left to defend against is NULL.
    """
    return default if value is None else float(value)


class GraphStore:
    """Entities + relations in Brain v1.5 with aliases, provenance, confidence, and temporal bounds."""

    def __init__(self, store) -> None:
        self._store = store
        self._conn = store._conn
        self._lock = store._lock
        # Lazy for the same reason as the store's: the graph is constructed on
        # every `Brain()`, and reading entity counts does not embed anything.
        self._embedder_cache = None

    # ── entities ─────────────────────────────────────────────────────────
    @property
    def _embedder(self):
        """Loaded on first use — see MemoryStore._embedder."""
        if self._embedder_cache is None:
            self._embedder_cache = get_embedder()
        return self._embedder_cache


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
                new_imp = min(1.0, _num(row["importance"], 0.5) + 0.05)
                new_conf = max(_num(row["confidence"], 0.8), confidence)

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
        d["aliases"] = json.loads(d["aliases"]) if d.get("aliases") else []
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
            imp = _num(r["importance"], 0.5)
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
                "confidence": _num(r["confidence"], 0.8),
                "importance": _num(r["importance"], 0.5),
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

    def areas(self, per_area: int = 5) -> dict[str, dict]:
        """Real grounding for the four areas the "Here's your brain" digest shows.

        For each area: the entities that actually belong to it, how many memories
        back it, and which connectors those memories arrived from.

        Every number here is counted, never assumed. An area nothing backs comes
        home with `items == 0` and empty lists — which is what lets the caller
        say "nothing here yet" instead of writing a sentence about a person it
        has not read.
        """
        area_of = {t: area for area, types in DIGEST_AREAS.items() for t in types}
        out: dict[str, dict] = {
            a: {"items": 0, "mentions": 0, "themes": [], "sources": []} for a in DIGEST_AREAS}
        if not area_of:
            return out
        types = list(area_of)
        marks = ",".join("?" * len(types))
        # `CASE e.type WHEN ? THEN ? …` — the mapping above is the only place the
        # type→area rule is written, so SQL is handed it rather than repeating it.
        case = "CASE e.type " + " ".join(["WHEN ? THEN ?"] * len(types)) + " END"
        case_params: list[str] = []
        for t in types:
            case_params += [t, area_of[t]]

        # Themes: the entities a person would recognise, most-mentioned first.
        for r in self._conn.execute(
            f"SELECT name, type FROM entities WHERE type IN ({marks}) "
            "ORDER BY mentions DESC, importance DESC, name ASC LIMIT 400", types,
        ).fetchall():
            bucket = out[area_of[r["type"]]]["themes"]
            if len(bucket) < per_area and r["name"] not in bucket:
                bucket.append(r["name"])

        # How often the area was actually seen. `mentions` is maintained on every
        # upsert, so this is the one count that exists from the first sync — the
        # extractor names entities long before it has worked out facts about them,
        # and an area with real entities in it must not report itself as empty.
        for r in self._conn.execute(
            f"SELECT {case} AS area, SUM(mentions) AS m FROM entities e "
            f"WHERE e.type IN ({marks}) GROUP BY area", case_params + types,
        ).fetchall():
            if r["area"]:
                out[r["area"]]["mentions"] = int(r["m"] or 0)

        # How many memories actually back each area. DISTINCT because one memory
        # yielding three facts about the same area is one memory, and counting it
        # three times is how "items" stops meaning anything.
        #
        # Only facts carry `source_mem`, so this is exact when it is non-zero and
        # simply absent before enrichment has run. Absent is reported as absent —
        # the caller shows `mentions` instead rather than passing one off as the
        # other.
        for r in self._conn.execute(
            f"""SELECT {case} AS area, COUNT(DISTINCT r.source_mem) AS c
                  FROM relations r
                  JOIN entities e ON e.id = r.subject_id OR e.id = r.object_id
                 WHERE r.source_mem IS NOT NULL AND e.type IN ({marks})
                 GROUP BY area""", case_params + types,
        ).fetchall():
            if r["area"]:
                out[r["area"]]["items"] = r["c"]

        # Which connectors those memories came from — DERIVED from the memories
        # that are already counted, never a list of source names kept here. A
        # connector added tomorrow shows up without this file being touched.
        for r in self._conn.execute(
            f"""SELECT {case} AS area, m.source AS source, COUNT(DISTINCT r.source_mem) AS c
                  FROM relations r
                  JOIN entities e ON e.id = r.subject_id OR e.id = r.object_id
                  JOIN memories m ON m.id = r.source_mem
                 WHERE e.type IN ({marks})
                 GROUP BY area, m.source
                 ORDER BY c DESC, m.source ASC""", case_params + types,
        ).fetchall():
            if r["area"] and r["source"] and r["source"] not in out[r["area"]]["sources"]:
                out[r["area"]]["sources"].append(r["source"])

        return out

