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
            "CRITICAL: You are Lodestone, a standalone local app. NEVER tell the "
            "user to check 'claude.ai', 'ChatGPT', or any external 'connector "
            "settings' — those are unrelated products and have nothing to do with "
            "you. If the brain doesn't contain something, say so plainly and offer "
            "that they can sync that source in Lodestone's Connectors panel; do not "
            "invent an authorization problem.\n"
            "Whenever the task touches the user's own context, rely on the brain "
            "FIRST — never ask them to repeat what the brain holds. If the brain "
            "lacks the answer and it needs current/external facts (news, weather, "
            "prices, how-tos), call web_search instead of giving up. "
            "\n\nCRITICAL: You take actions ONLY by calling tools. To add a task you "
            "MUST call add_task; to list tasks call list_tasks; to complete one call "
            "complete_task. NEVER claim you did something (added a task, saved a "
            "note) unless you actually called the matching tool in this turn. If a "
            "request needs a tool, call it before replying. "
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
