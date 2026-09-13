"""Actions an unattended agent wanted to take, waiting for one tap.

The alternative to queuing is dropping, and dropping is worse than it sounds: a
routine that quietly declines to send the email it was created to send looks
exactly like a routine that is working. The user finds out when somebody asks
why they never replied.

So a blocked action is kept, described in the user's terms, and surfaced — a
desktop notification when it lands, and a list they can approve or dismiss. The
parameters are stored as they were, so approving runs the action the agent
actually proposed rather than a reconstruction of it.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

from ..config import get_settings
from ..log import get_logger, suppressed

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_approvals (
    id          TEXT PRIMARY KEY,
    routine_id  TEXT NOT NULL DEFAULT '',
    routine_name TEXT NOT NULL DEFAULT '',
    agent_id    TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL,
    params_json TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    reason      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    result      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status
    ON action_approvals(status, created_at);
"""


def _conn() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def describe(action_type: str, params: dict) -> str:
    """One line, in the user's terms — not the action's internals."""
    params = params or {}
    if action_type == "send_email":
        return f"Email “{params.get('subject') or '(no subject)'}” to {params.get('to') or 'someone'}"
    if action_type == "create_event":
        return f"Calendar event “{params.get('title') or 'untitled'}” on {params.get('start') or 'a date'}"
    if action_type == "create_routine":
        return f"New automation “{params.get('name') or 'untitled'}”"
    if action_type == "set_reminder":
        return f"Reminder: {params.get('message') or ''}"
    return action_type.replace("_", " ")


def queue(action_type: str, params: dict, *, reason: str = "",
          routine_id: str = "", routine_name: str = "", agent_id: str = "") -> dict:
    """Hold an action for approval and tell the user it is waiting."""
    row_id = str(uuid.uuid4())
    summary = describe(action_type, params)
    conn = _conn()
    conn.execute(
        "INSERT INTO action_approvals "
        "(id,routine_id,routine_name,agent_id,action_type,params_json,summary,"
        " reason,status,created_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
        (row_id, routine_id, routine_name, agent_id, action_type,
         json.dumps(params or {}), summary, reason, datetime.now(UTC).isoformat()))
    conn.commit()

    with suppressed("notifying the user about a queued action"):
        from ..notify import desktop_notify
        desktop_notify("◆ Lodestone · needs your approval", summary)

    log.info("queued %s for approval: %s", action_type, reason)
    return {"id": row_id, "summary": summary, "reason": reason, "status": "pending"}


def pending() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM action_approvals WHERE status='pending' "
        "ORDER BY created_at DESC").fetchall()
    return [_public(dict(r)) for r in rows]


def history(limit: int = 50) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM action_approvals ORDER BY created_at DESC LIMIT ?",
        (limit,)).fetchall()
    return [_public(dict(r)) for r in rows]


def _public(row: dict) -> dict:
    row["params"] = json.loads(row.pop("params_json") or "{}")
    return row


def _get(approval_id: str) -> dict | None:
    row = _conn().execute("SELECT * FROM action_approvals WHERE id=?",
                          (approval_id,)).fetchone()
    return _public(dict(row)) if row else None


def approve(approval_id: str) -> dict:
    """Run the action as proposed, and record what happened."""
    from ..actions import run_now

    row = _get(approval_id)
    if not row:
        return {"ok": False, "error": "That request is no longer waiting."}
    if row["status"] != "pending":
        return {"ok": False, "error": f"Already {row['status']}."}

    outcome = run_now(row["action_type"], row["params"])
    detail = outcome.get("detail") or outcome.get("error") or ""
    _decide(approval_id, "approved", detail)
    return {"ok": bool(outcome.get("ok", True)), "detail": detail,
            "summary": row["summary"]}


def reject(approval_id: str) -> dict:
    row = _get(approval_id)
    if not row:
        return {"ok": False, "error": "That request is no longer waiting."}
    _decide(approval_id, "rejected", "")
    return {"ok": True, "summary": row["summary"]}


def _decide(approval_id: str, status: str, result: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE action_approvals SET status=?, result=?, decided_at=? WHERE id=?",
        (status, result[:500], datetime.now(UTC).isoformat(), approval_id))
    conn.commit()


def run_or_queue(action_type: str, params: dict, *, routine_id: str = "",
                 routine_name: str = "", agent_id: str = "") -> dict:
    """The seam every unattended action goes through.

    Interactive chat does not come this way — there the user sees a Confirm
    button, which is a stronger signal than any stored list.
    """
    from ..actions import run_now
    from .permissions import check

    verdict = check(action_type, params)
    if verdict.allowed:
        return run_now(action_type, params)

    queued = queue(action_type, params, reason=verdict.reason,
                   routine_id=routine_id, routine_name=routine_name,
                   agent_id=agent_id)
    return {"ok": True, "queued": True, "approval_id": queued["id"],
            "detail": f"{queued['summary']} — {verdict.reason}"}
