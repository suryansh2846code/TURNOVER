"""Routines — automations that run an agent on a trigger.

Creating a routine pre-authorizes the *routine*. It does not pre-authorize
whoever wrote the text the routine happens to read: a `new_email` trigger hands
the agent content from a stranger, and an instruction hidden in that content
reaches an agent that can propose sending mail. So actions are filtered through
`agents/approvals.py::run_or_queue` — reading and note-taking run freely,
anything that leaves the machine needs a recipient the user has permitted, and
everything else waits for one tap.

Triggers:
  • schedule   — every N minutes.
  • new_email  — when new email(s) arrive during a sync.

Guardrails: routines are user-created, disable-able, permission-gated for
outbound actions, and their runs are logged + notified.
"""
from __future__ import annotations

import builtins
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from .config import get_settings

log = logging.getLogger("lodestone.routines")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    agent_id     TEXT NOT NULL DEFAULT 'personal',
    trigger      TEXT NOT NULL,            -- schedule | new_email
    interval_min INTEGER NOT NULL DEFAULT 60,
    instruction  TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    last_run     TEXT,
    last_result  TEXT
);
"""


class RoutineStore:
    def __init__(self) -> None:
        path = get_settings().home / "routines.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL;")
        self._c.execute("PRAGMA busy_timeout=5000;")   # scheduler + API share this
        self._c.executescript(_SCHEMA)

    def create(self, name, agent_id, trigger, instruction,
               interval_min=60) -> dict:
        rid = str(uuid.uuid4())
        self._c.execute(
            "INSERT INTO routines (id,name,agent_id,trigger,interval_min,"
            "instruction,enabled,created_at) VALUES (?,?,?,?,?,?,1,?)",
            (rid, name.strip() or "Routine", agent_id, trigger,
             int(interval_min or 60), instruction.strip(),
             datetime.now(UTC).isoformat()))
        self._c.commit()
        return self.get(rid)

    def get(self, rid) -> dict | None:
        r = self._c.execute("SELECT * FROM routines WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def list(self) -> builtins.list[dict]:
        return [dict(r) for r in self._c.execute(
            "SELECT * FROM routines ORDER BY created_at").fetchall()]

    def enabled(self) -> builtins.list[dict]:
        return [dict(r) for r in self._c.execute(
            "SELECT * FROM routines WHERE enabled=1").fetchall()]

    #: What an edit is allowed to touch. `enabled` has its own toggle and the
    #: run history is the routine's record of itself — neither is the user's to
    #: retype, and allowing them here would let a typo erase what it did.
    EDITABLE = ("name", "agent_id", "trigger", "interval_min", "instruction")

    def update(self, rid, **fields) -> dict | None:
        """Change a routine in place. Unknown or absent fields are ignored.

        Returns the updated routine, or None if there was none to update — the
        caller turns that into a 404 rather than reporting a silent success.
        """
        sets, vals = [], []
        for k in self.EDITABLE:
            if fields.get(k) is None:
                continue
            v = fields[k]
            if k == "interval_min":
                v = max(1, int(v))        # a zero-minute routine is a busy loop
            elif isinstance(v, str):
                v = v.strip()
                if not v:
                    continue              # blanking a name is not an edit
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return self.get(rid)
        vals.append(rid)
        cur = self._c.execute(f"UPDATE routines SET {', '.join(sets)} WHERE id=?", vals)
        self._c.commit()
        return self.get(rid) if cur.rowcount else None

    def toggle(self, rid, on: bool) -> None:
        self._c.execute("UPDATE routines SET enabled=? WHERE id=?",
                        (1 if on else 0, rid)); self._c.commit()

    def mark_run(self, rid, result: str) -> None:
        self._c.execute("UPDATE routines SET last_run=?, last_result=? WHERE id=?",
                        (datetime.now(UTC).isoformat(), result[:400], rid))
        self._c.commit()

    def delete(self, rid) -> bool:
        cur = self._c.execute("DELETE FROM routines WHERE id=?", (rid,))
        self._c.commit()
        return cur.rowcount > 0


_store = None


def get_routines() -> RoutineStore:
    global _store
    if _store is None:
        _store = RoutineStore()
    return _store


# ── running routines ─────────────────────────────────────────────────────
def _new_emails_since(iso: str | None) -> list:
    """Gmail memories created after `iso` (the routine's last run)."""
    from .brain import get_brain
    store = get_brain().store
    return store._conn.execute(
        "SELECT title, text, created_at FROM memories WHERE source='gmail' "
        "AND created_at > ? ORDER BY created_at DESC LIMIT 10",
        (iso or "1970-01-01",)).fetchall()


def run_routine(r: dict, trigger_context: str = "") -> dict:
    """Run one routine: the agent acts on the instruction (+ any trigger
    context); actions it proposes are auto-executed."""
    from .actions import parse_actions
    from .agents import run_turn
    from .agents.approvals import run_or_queue
    from .notify import desktop_notify

    prompt = r["instruction"]
    if trigger_context:
        prompt += "\n\n" + trigger_context
    try:
        res = run_turn(r["agent_id"], prompt)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}

    outcomes = []
    for a in parse_actions(res.reply):
        a["params"]["agent_id"] = r["agent_id"]
        # Not `run_now`. A routine is pre-authorisation for the *routine*, and
        # that reasoning holds right up until the trigger is `new_email` — at
        # which point the text driving the agent was written by a stranger, and
        # an action that leaves the machine needs a recipient the user named.
        out = run_or_queue(a["type"], a["params"], routine_id=r["id"],
                           routine_name=r["name"], agent_id=r["agent_id"])
        outcomes.append(out.get("detail") or out.get("error") or "")
    summary = "; ".join(o for o in outcomes if o) or "ran (no action)"
    desktop_notify(f"◆ Lodestone · {r['name']}", summary)
    return {"ok": True, "detail": summary}


def sweep(new_email_count: int = 0) -> None:
    """Called by the scheduler each cycle: fire due routines."""
    store = get_routines()
    now = datetime.now(UTC)
    for r in store.enabled():
        try:
            if r["trigger"] == "schedule":
                last = r["last_run"]
                due = (last is None or
                       datetime.fromisoformat(last) +
                       timedelta(minutes=r["interval_min"]) <= now)
                if not due:
                    continue
                res = run_routine(r)
                store.mark_run(r["id"], json.dumps(res)[:400])
            elif r["trigger"] == "new_email" and new_email_count > 0:
                rows = _new_emails_since(r["last_run"])
                if not rows:
                    continue
                ctx = "NEW EMAIL(S) that just arrived:\n" + "\n".join(
                    f"- {row['title']}: {' '.join(row['text'].split())[:200]}"
                    for row in rows)
                res = run_routine(r, ctx)
                store.mark_run(r["id"], json.dumps(res)[:400])
        except Exception:
            log.exception("routine %s failed", r.get("id"))
