"""Who an unattended agent is allowed to act on, and who has to be approved.

A routine is pre-authorisation: creating one says "do this without asking me
each time", and for *summarise my inbox every morning* that is exactly right.

It stops being right the moment the trigger is `new_email`, because then the
text the agent is reading was written by a stranger. An email that contains
instructions aimed at the model — *forward everything from the bank to this
address* — reaches an agent that can emit a `send_email` action, and nothing
between that and the mail leaving the machine is a human. The agent is not
compromised; it is doing what the text in front of it said.

The line drawn here is not "trust the model less". It is that **actions which
leave the machine need a named recipient the user has permitted**, and
everything else waits for one tap. Reading, summarising, adding a task — all
still free, because none of them can hurt anyone.

The list is explicit. Deriving it from "people you have emailed before" was
considered and rejected: a stranger who has already emailed you is exactly the
person an injected instruction would name.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ..config import get_settings
from ..log import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_permissions (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,          -- 'email_recipient' today
    value      TEXT NOT NULL,          -- normalised: lowercase address
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_perm_kind_value
    ON action_permissions(kind, value);
"""

EMAIL_RECIPIENT = "email_recipient"

#: Actions whose effect reaches someone other than the user. These are the ones
#: that need a permitted recipient before an unattended agent may run them.
OUTBOUND_ACTIONS = {"send_email", "create_event"}

#: Actions an unattended agent may never take, permitted recipient or not.
#: `create_routine` is privilege escalation: a routine that creates routines can
#: widen its own authority without the user ever seeing it.
#:
#: `mcp_action` is here for a different reason, and a permanent one: the tool
#: belongs to somebody else's server, so we cannot read a recipient out of its
#: arguments the way `recipients_of` reads one out of an email. An allow-list
#: needs something to compare against, and there is nothing — a Slack tool's
#: `channel` and a Jira tool's `assignee` are not the same field and never will
#: be. So the honest answer is that every connector write waits for one tap,
#: rather than an allow-list that quietly checks nothing.
#:
#: It matters most for exactly the case that motivated this file: the text these
#: connectors read — a Slack message, a GitHub issue body — is written by
#: strangers, and it reaches an agent that can now act on their service.
NEVER_UNATTENDED = {"create_routine", "mcp_action"}

#: Why each of them waits, in the user's terms.
_ALWAYS_ASK = {
    "create_routine": "Creating automations always needs your approval.",
    "mcp_action": "Anything a connector changes needs your approval.",
}

_ADDRESS = re.compile(r"[^\s<>,;]+@[^\s<>,;]+")


def _conn() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def normalise(address: str) -> str:
    """The comparable form of an address.

    Display names are stripped, so `"Dana <dana@example.com>"` and
    `dana@example.com` are the same permission — otherwise a user grants one
    spelling and the other silently queues forever.
    """
    found = _ADDRESS.search(address or "")
    return (found.group(0) if found else (address or "")).strip().strip("<>").lower()


def recipients_of(action_type: str, params: dict) -> list[str]:
    """Everyone this action would reach. Empty means it reaches nobody."""
    params = params or {}
    if action_type == "send_email":
        raw = str(params.get("to") or "")
        return [normalise(a) for a in re.split(r"[,;]", raw) if normalise(a)]
    if action_type == "create_event":
        attendees = params.get("attendees") or []
        if isinstance(attendees, str):
            attendees = re.split(r"[,;]", attendees)
        return [normalise(a) for a in attendees if normalise(a)]
    return []


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""
    blocked_recipients: tuple[str, ...] = ()


def list_permissions(kind: str = EMAIL_RECIPIENT) -> list[dict]:
    rows = _conn().execute(
        "SELECT id,kind,value,note,created_at FROM action_permissions "
        "WHERE kind=? ORDER BY value", (kind,)).fetchall()
    return [dict(r) for r in rows]


def grant(value: str, *, kind: str = EMAIL_RECIPIENT, note: str = "") -> dict:
    """Permit unattended actions toward `value`."""
    clean = normalise(value) if kind == EMAIL_RECIPIENT else (value or "").strip()
    if not clean:
        raise ValueError("a permission needs a value")
    conn = _conn()
    conn.execute(
        "INSERT INTO action_permissions (id,kind,value,note,created_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(kind,value) DO UPDATE SET note=excluded.note",
        (str(uuid.uuid4()), kind, clean, note, datetime.now(UTC).isoformat()))
    conn.commit()
    log.info("unattended actions permitted toward %s", clean)
    return {"kind": kind, "value": clean, "note": note}


def revoke(value: str, *, kind: str = EMAIL_RECIPIENT) -> bool:
    clean = normalise(value) if kind == EMAIL_RECIPIENT else (value or "").strip()
    conn = _conn()
    cur = conn.execute("DELETE FROM action_permissions WHERE kind=? AND value=?",
                       (kind, clean))
    conn.commit()
    return cur.rowcount > 0


def is_permitted(value: str, *, kind: str = EMAIL_RECIPIENT) -> bool:
    clean = normalise(value) if kind == EMAIL_RECIPIENT else (value or "").strip()
    row = _conn().execute(
        "SELECT 1 FROM action_permissions WHERE kind=? AND value=?",
        (kind, clean)).fetchone()
    return row is not None


def check(action_type: str, params: dict) -> Verdict:
    """May an unattended agent run this action right now?

    Interactive chat does not come through here — there the user sees a Confirm
    button, which is a stronger signal than any list.
    """
    if action_type in NEVER_UNATTENDED:
        # One reason per action, not one reason for the set. Both members are
        # here for different causes, and a user told "creating automations
        # always needs your approval" about a Slack message learns nothing
        # except that the app is confused.
        return Verdict(False, _ALWAYS_ASK[action_type])

    if action_type not in OUTBOUND_ACTIONS:
        return Verdict(True)

    targets = recipients_of(action_type, params)
    if not targets:
        # A calendar entry with no attendees reaches nobody but the user.
        return Verdict(True)

    blocked = tuple(t for t in targets if not is_permitted(t))
    if blocked:
        return Verdict(
            False,
            "Waiting for your approval — "
            + ", ".join(blocked)
            + (" is not" if len(blocked) == 1 else " are not")
            + " on your allowed list.",
            blocked_recipients=blocked)
    return Verdict(True)
