"""Scheduled actions — a confirmed action (send email / create event) that fires
automatically at a future time. The user confirms once now (content + time);
the scheduler executes it at fire_at and notifies the result.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from .config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_actions (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    params     TEXT NOT NULL DEFAULT '{}',
    fire_at    TEXT NOT NULL,
    agent_id   TEXT,
    created_at TEXT NOT NULL,
    fired      INTEGER NOT NULL DEFAULT 0,
    result     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sched_fire ON scheduled_actions(fired, fire_at);
"""


class ScheduledStore:
    def __init__(self) -> None:
        path = get_settings().home / "reminders.db"   # share the file
        path.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL;")
        self._c.execute("PRAGMA busy_timeout=5000;")   # scheduler + API share this
        self._c.executescript(_SCHEMA)

    def add(self, type: str, params: dict, fire_at: str,
            agent_id: str | None = None) -> dict:
        sid = str(uuid.uuid4())
        self._c.execute(
            "INSERT INTO scheduled_actions (id,type,params,fire_at,agent_id,"
            "created_at,fired) VALUES (?,?,?,?,?,?,0)",
            (sid, type, json.dumps(params), fire_at, agent_id,
             datetime.now().astimezone().isoformat()))
        self._c.commit()
        return dict(self._c.execute(
            "SELECT * FROM scheduled_actions WHERE id=?", (sid,)).fetchone())

    def due(self) -> list[dict]:
        now = datetime.now().astimezone().isoformat()
        rows = self._c.execute(
            "SELECT * FROM scheduled_actions WHERE fired=0 AND fire_at<=?",
            (now,)).fetchall()
        return [dict(r) for r in rows]

    def mark_done(self, sid: str, result: str) -> None:
        self._c.execute("UPDATE scheduled_actions SET fired=1, result=? WHERE id=?",
                        (result, sid))
        self._c.commit()

    def upcoming(self, limit: int = 20) -> list[dict]:
        rows = self._c.execute(
            "SELECT * FROM scheduled_actions WHERE fired=0 ORDER BY fire_at LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete(self, sid: str) -> bool:
        cur = self._c.execute("DELETE FROM scheduled_actions WHERE id=?", (sid,))
        self._c.commit()
        return cur.rowcount > 0


_store = None


def get_scheduled() -> ScheduledStore:
    global _store
    if _store is None:
        _store = ScheduledStore()
    return _store
