"""Low-level CRUD + the materialized 'current' views over the canonical Brain."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...config import get_settings
from .db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


class CanonicalStore:
    """Owns brain.db. Thread-safe over one shared connection + lock (matches the
    source store's model). All writes go through the supersession-aware helpers
    in curate.py, not raw SQL callers."""

    def __init__(self, db_path: Path | None = None) -> None:
        s = get_settings()
        self.db_path = Path(db_path) if db_path else (s.home / "brain.db")
        self._conn = connect(self.db_path)
        self._lock = threading.Lock()

    # ── entities & identity ───────────────────────────────────────────────
    def create_entity(self, type: str, canonical_name: str) -> str:
        eid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO entities (id,type,canonical_name,status,created_at,updated_at)"
                " VALUES (?,?,?,'active',?,?)",
                (eid, type, canonical_name.strip(), _now(), _now()))
            self._conn.commit()
        return eid

    def get_entity(self, entity_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return dict(r) if r else None

    def rename_entity(self, entity_id: str, name: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE entities SET canonical_name=?, updated_at=? WHERE id=?",
                               (name.strip(), _now(), entity_id))
            self._conn.commit()

    def set_entity_status(self, entity_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE entities SET status=?, updated_at=? WHERE id=?",
                               (status, _now(), entity_id))
            self._conn.commit()

    def entity_by_name(self, type: str, name: str) -> dict | None:
        r = self._conn.execute(
            "SELECT * FROM entities WHERE type=? AND lower(canonical_name)=?",
            (type, _norm(name))).fetchone()
        return dict(r) if r else None

    def add_identifier(self, entity_id: str, kind: str, value: str) -> bool:
        """Attach a stable id. Returns False if it already maps elsewhere."""
        v = _norm(value)
        if not v:
            return False
        existing = self._conn.execute(
            "SELECT entity_id FROM entity_identifiers WHERE kind=? AND value_normalized=?",
            (kind, v)).fetchone()
        if existing:
            return existing["entity_id"] == entity_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO entity_identifiers (id,entity_id,kind,value_normalized,created_at)"
                " VALUES (?,?,?,?,?)", (_uid(), entity_id, kind, v, _now()))
            self._conn.commit()
        return True

    def entity_for_identifier(self, kind: str, value: str) -> str | None:
        r = self._conn.execute(
            "SELECT entity_id FROM entity_identifiers WHERE kind=? AND value_normalized=?",
            (kind, _norm(value))).fetchone()
        return r["entity_id"] if r else None

    def identifiers_for(self, entity_id: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT kind,value_normalized FROM entity_identifiers WHERE entity_id=?",
            (entity_id,)).fetchall()]

    def list_entities(self, type: str | None = None, status: str = "active") -> list[dict]:
        if type:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE type=? AND status=? ORDER BY updated_at DESC",
                (type, status)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE status=? ORDER BY updated_at DESC",
                (status,)).fetchall()
        return [dict(r) for r in rows]

    # ── claims (append-only, versioned) ───────────────────────────────────
    def insert_claim(self, *, entity_id: str | None, section: str, type: str,
                     value: Any, state: str, confidence: str,
                     source_timestamp: str | None, claim_key: str,
                     supersedes: str | None = None) -> str:
        cid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO claims (id,entity_id,section,type,value_json,state,"
                "confidence,freshness,valid_from,valid_to,source_timestamp,"
                "last_confirmed_at,supersedes_claim_id,claim_key,created_at)"
                " VALUES (?,?,?,?,?,?,?,'fresh',?,NULL,?,?,?,?,?)",
                (cid, entity_id, section, type, json.dumps(value), state, confidence,
                 _now(), source_timestamp, source_timestamp or _now(), supersedes,
                 claim_key, _now()))
            self._conn.commit()
        return cid

    def current_claim_by_key(self, claim_key: str) -> dict | None:
        r = self._conn.execute(
            "SELECT * FROM claims WHERE claim_key=? AND state IN ('current','open') "
            "ORDER BY created_at DESC LIMIT 1", (claim_key,)).fetchone()
        return self._claim_row(r) if r else None

    def supersede_claim(self, claim_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE claims SET state='historical', valid_to=? WHERE id=?",
                (_now(), claim_id))
            self._conn.commit()

    def touch_claim(self, claim_id: str, source_timestamp: str | None) -> None:
        """Re-confirming an unchanged claim: bump last_confirmed_at (freshness)."""
        with self._lock:
            self._conn.execute(
                "UPDATE claims SET last_confirmed_at=?, source_timestamp="
                "COALESCE(?, source_timestamp), freshness='fresh' WHERE id=?",
                (_now(), source_timestamp, claim_id))
            self._conn.commit()

    def resolve_claim(self, claim_id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE claims SET state='resolved', valid_to=? WHERE id=?",
                               (_now(), claim_id))
            self._conn.commit()

    def set_freshness(self, claim_id: str, freshness: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE claims SET freshness=? WHERE id=?",
                               (freshness, claim_id))
            self._conn.commit()

    def get_claim(self, claim_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        return self._claim_row(r) if r else None

    def current_claims(self, *, entity_id: str | None = "__any__",
                       section: str | None = None) -> list[dict]:
        q = "SELECT * FROM claims WHERE state IN ('current','open')"
        args: list = []
        if entity_id != "__any__":
            if entity_id is None:
                q += " AND entity_id IS NULL"
            else:
                q += " AND entity_id=?"
                args.append(entity_id)
        if section:
            q += " AND section=?"
            args.append(section)
        q += " ORDER BY created_at DESC"
        return [self._claim_row(r) for r in self._conn.execute(q, args).fetchall()]

    def claim_history(self, claim_key: str) -> list[dict]:
        return [self._claim_row(r) for r in self._conn.execute(
            "SELECT * FROM claims WHERE claim_key=? ORDER BY created_at ASC",
            (claim_key,)).fetchall()]

    @staticmethod
    def _claim_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["value"] = json.loads(d.pop("value_json"))
        except Exception:
            d["value"] = d.pop("value_json", None)
        return d

    # ── events (immutable timeline) ───────────────────────────────────────
    def add_event(self, *, event_type: str, occurred_at: str, summary: str,
                  entity_id: str | None = None,
                  source_timestamp: str | None = None) -> str:
        eid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (id,event_type,occurred_at,summary,entity_id,"
                "source_timestamp,created_at) VALUES (?,?,?,?,?,?,?)",
                (eid, event_type, occurred_at, summary, entity_id,
                 source_timestamp, _now()))
            self._conn.commit()
        return eid

    def timeline(self, limit: int = 200, entity_id: str | None = None) -> list[dict]:
        if entity_id:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE entity_id=? ORDER BY occurred_at DESC LIMIT ?",
                (entity_id, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY occurred_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def event_exists(self, event_type: str, occurred_at: str, summary: str) -> bool:
        r = self._conn.execute(
            "SELECT 1 FROM events WHERE event_type=? AND occurred_at=? AND summary=?",
            (event_type, occurred_at, summary)).fetchone()
        return r is not None

    # ── evidence ──────────────────────────────────────────────────────────
    def add_evidence(self, *, claim_id: str | None = None, event_id: str | None = None,
                     source_type: str, source_uri: str | None = None,
                     external_id: str | None = None, excerpt: str | None = None) -> str:
        vid = _uid()
        h = hashlib.sha256((excerpt or "").encode()).hexdigest()[:16] if excerpt else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO evidence (id,claim_id,event_id,source_type,source_uri,"
                "external_id,excerpt,excerpt_hash,captured_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (vid, claim_id, event_id, source_type, source_uri, external_id,
                 (excerpt or "")[:500], h, _now()))
            self._conn.commit()
        return vid

    def evidence_for_claim(self, claim_id: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM evidence WHERE claim_id=? ORDER BY captured_at DESC",
            (claim_id,)).fetchall()]

    # ── tasks ─────────────────────────────────────────────────────────────
    def upsert_task(self, *, title: str, owner: str = "user", state: str = "open",
                    due_at: str | None = None, entity_id: str | None = None,
                    source_timestamp: str | None = None) -> str:
        existing = self._conn.execute(
            "SELECT id FROM tasks WHERE title=? AND (entity_id IS ? OR entity_id=?)",
            (title, entity_id, entity_id)).fetchone()
        if existing:
            with self._lock:
                self._conn.execute(
                    "UPDATE tasks SET state=?, due_at=COALESCE(?,due_at), "
                    "last_confirmed_at=? WHERE id=?",
                    (state, due_at, _now(), existing["id"]))
                self._conn.commit()
            return existing["id"]
        tid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id,title,owner,state,due_at,entity_id,"
                "source_timestamp,last_confirmed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (tid, title, owner, state, due_at, entity_id, source_timestamp,
                 _now(), _now()))
            self._conn.commit()
        return tid

    def set_task_state(self, task_id: str, state: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tasks SET state=?, last_confirmed_at=? WHERE id=?",
                               (state, _now(), task_id))
            self._conn.commit()

    def open_tasks(self, entity_id: str | None = None) -> list[dict]:
        if entity_id:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE state IN ('open','waiting') AND entity_id=? "
                "ORDER BY COALESCE(due_at,'9999') ASC", (entity_id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE state IN ('open','waiting') "
                "ORDER BY COALESCE(due_at,'9999') ASC").fetchall()
        return [dict(r) for r in rows]

    # ── candidates (review queue) ─────────────────────────────────────────
    def add_candidate(self, *, kind: str, payload: dict, status: str,
                      reason: str = "", source_type: str | None = None,
                      source_uri: str | None = None) -> str:
        cid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO candidates (id,kind,status,reason,payload_json,"
                "source_type,source_uri,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, kind, status, reason, json.dumps(payload), source_type,
                 source_uri, _now(), _now() if status != "pending" else None))
            self._conn.commit()
        return cid

    def pending_candidates(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM candidates WHERE status IN ('pending','needs_review') "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._cand_row(r) for r in rows]

    def get_candidate(self, cid: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
        return self._cand_row(r) if r else None

    def set_candidate_status(self, cid: str, status: str, reason: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE candidates SET status=?, reason=COALESCE(NULLIF(?,''),reason),"
                " decided_at=? WHERE id=?", (status, reason, _now(), cid))
            self._conn.commit()

    @staticmethod
    def _cand_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            d["payload"] = {}
        return d

    # ── evaluation fixtures ───────────────────────────────────────────────
    def add_eval_case(self, *, query: str, expected_claim_ids=None,
                      expected_entity_ids=None, expected_source_ids=None,
                      freshness_expect: str | None = None) -> str:
        cid = _uid()
        with self._lock:
            self._conn.execute(
                "INSERT INTO evaluation_cases (id,query,expected_claim_ids,"
                "expected_entity_ids,expected_source_ids,freshness_expect,created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (cid, query, json.dumps(expected_claim_ids or []),
                 json.dumps(expected_entity_ids or []),
                 json.dumps(expected_source_ids or []), freshness_expect, _now()))
            self._conn.commit()
        return cid

    def eval_cases(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM evaluation_cases").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("expected_claim_ids", "expected_entity_ids", "expected_source_ids"):
                d[k] = json.loads(d[k])
            out.append(d)
        return out

    # ── housekeeping ──────────────────────────────────────────────────────
    def stats(self) -> dict:
        c = self._conn
        def n(sql, *a): return c.execute(sql, a).fetchone()[0]
        return {
            "entities": n("SELECT COUNT(*) FROM entities WHERE status='active'"),
            "claims_current": n("SELECT COUNT(*) FROM claims WHERE state IN ('current','open')"),
            "claims_total": n("SELECT COUNT(*) FROM claims"),
            "events": n("SELECT COUNT(*) FROM events"),
            "tasks_open": n("SELECT COUNT(*) FROM tasks WHERE state IN ('open','waiting')"),
            "pending_review": n("SELECT COUNT(*) FROM candidates WHERE status IN ('pending','needs_review')"),
            "by_entity_type": {r["type"]: r["c"] for r in c.execute(
                "SELECT type, COUNT(*) c FROM entities WHERE status='active' GROUP BY type")},
        }

    def wipe(self) -> None:
        with self._lock:
            for t in ("entities", "entity_identifiers", "claims", "events",
                      "evidence", "tasks", "candidates"):
                self._conn.execute(f"DELETE FROM {t}")
            self._conn.commit()


@lru_cache
def get_canonical_store() -> CanonicalStore:
    return CanonicalStore()
