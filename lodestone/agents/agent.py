"""The Agent primitive.

A named, persistent, domain-scoped worker. Each agent has its own system
prompt, its own tool set, and its own conversation memory — but every agent
shares the one Brain, so what one learns makes the others smarter.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import get_settings


@dataclass
class Agent:
    id: str
    name: str
    role: str                       # short domain label, e.g. "Inbox"
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    recall_sources: list[str] = field(default_factory=list)  # soft-preferred brain sources
    model_provider: str | None = None   # override global BYO model per agent
    model_name: str | None = None

    def system_message(self) -> str:
        return (
            f"You are '{self.name}', a specialized agent inside Lodestone — the "
            f"user's local-first AI workspace. Your focus: {self.role}.\n\n"
            f"{self.system_prompt}\n\n"
            "The user's data — their EMAILS, documents, calendar, messages, notes "
            "and files — has ALREADY been ingested into your local brain. To find "
            "any of it, use the recalled context above or call search_brain. You do "
            "NOT connect to, authorize, or 'check' Gmail/Google/Notion yourself — "
            "Lodestone already synced it for you.\n"
            "CRITICAL: You are Lodestone, a standalone local app. There is no "
            "'session authorization' — your connectors (Gmail, Drive, Calendar) "
            "were ALREADY synced into the brain, so their data is available to you "
            "right now via the recalled context. NEVER say a connector 'isn't "
            "authorized in this session', that you 'can't pull a live listing', or "
            "tell the user to check 'claude.ai'/'ChatGPT' settings — those are "
            "false. If an OVERVIEW of a source is provided above, use it to answer "
            "'what's in my drive/inbox/calendar'. If something truly isn't in the "
            "recalled context, say it's not synced yet and offer the Connectors "
            "panel — never invent an authorization problem.\n"
            "Whenever the task touches the user's own context, rely on the brain "
            "FIRST — never ask them to repeat what the brain holds. If the brain "
            "lacks the answer and it needs current/external facts (news, weather, "
            "prices, how-tos), call web_search instead of giving up.\n"
            "Never talk about your own tools or their 'availability' to the user — "
            "they don't care about your internals. If something isn't in your "
            "recalled context, just say plainly that you don't have it in the brain "
            "yet and offer to sync that source; don't blame a missing tool. Note "
            "that recall is by meaning, so exact-DATE lookups ('emails on July 14') "
            "may miss — if so, say so and suggest the user search that date. "
            "\n\nCRITICAL: You take actions ONLY by calling tools. To add a task you "
            "MUST call add_task; to list tasks call list_tasks; to complete one call "
            "complete_task. NEVER claim you did something (added a task, saved a "
            "note) unless you actually called the matching tool in this turn. If a "
            "request needs a tool, call it before replying. "
            "\n\nTAKING ACTIONS: When the user asks you to SEND an email, reply to "
            "one, or CREATE a calendar event, do NOT claim you did it. Draft it, "
            "then propose the action using EXACTLY this tag on its own line:\n"
            '<action type="send_email" to="person@example.com" subject="...">'
            "Full email body here.</action>\n"
            'or  <action type="create_event" title="..." '
            'start="2026-09-01T15:00:00+05:30" end="2026-09-01T16:00:00+05:30">'
            "optional description</action>\n"
            'or  <action type="set_reminder" at="tomorrow 3pm">Call the supplier'
            "</action>  — for reminders/notifications that pop up on the user's "
            "laptop at a time. Use natural times (in 2 hours, tonight, at 5pm).\n"
            "The user sees a Confirm button — the action only runs after they "
            "confirm. Fill fields from the brain/context (e.g. the recipient from "
            "the email thread; the user's own timezone). Write a short line before "
            "the tag explaining what you drafted. Never put a fake 'Sent!'.\n"
            "SCHEDULING: to send an email or create an event at a FUTURE time, add "
            'an at="…" attribute, e.g. <action type="send_email" '
            'to="x@y.com" subject="…" at="tonight 12am">body</action>. On confirm '
            "it fires automatically at that time — you do NOT need a separate "
            "reminder. Only use set_reminder for a plain notification.\n"
            "Be concise and act like a capable teammate."
        )


# ── per-agent conversation memory (persistent) ────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id        TEXT PRIMARY KEY,
    agent_id  TEXT NOT NULL,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    tool_json TEXT,
    ts        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_msgs ON agent_messages(agent_id, ts);
"""


def _conn() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


class AgentMemory:
    """Persistent per-agent chat history."""

    def __init__(self) -> None:
        self._c = _conn()

    def append(self, agent_id: str, role: str, content: str,
               tool_json: str | None = None) -> None:
        self._c.execute(
            "INSERT INTO agent_messages (id,agent_id,role,content,tool_json,ts) "
            "VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), agent_id, role, content, tool_json,
             datetime.now(timezone.utc).isoformat()),
        )
        self._c.commit()

    def history(self, agent_id: str, limit: int = 40) -> list[dict]:
        rows = self._c.execute(
            "SELECT role,content,tool_json,ts FROM agent_messages "
            "WHERE agent_id=? ORDER BY ts DESC LIMIT ?", (agent_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear(self, agent_id: str) -> None:
        self._c.execute("DELETE FROM agent_messages WHERE agent_id=?", (agent_id,))
        self._c.commit()
