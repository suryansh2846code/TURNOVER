"""User-defined custom agents, persisted alongside the built-in presets."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from ..config import get_settings
from .agent import Agent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    tools         TEXT NOT NULL DEFAULT '[]',
    recall_sources TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);
"""


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or ("agent-" + uuid.uuid4().hex[:6])


class CustomAgentStore:
    def __init__(self) -> None:
        path = get_settings().home / "agents.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.executescript(_SCHEMA)

    def _row_to_agent(self, r: sqlite3.Row) -> Agent:
        return Agent(
            id=r["id"], name=r["name"], role=r["role"],
            system_prompt=r["system_prompt"],
            tools=json.loads(r["tools"]),
            recall_sources=json.loads(r["recall_sources"]),
        )

    def list(self) -> list[Agent]:
        rows = self._c.execute(
            "SELECT * FROM custom_agents ORDER BY created_at").fetchall()
        return [self._row_to_agent(r) for r in rows]

    def get(self, agent_id: str) -> Agent | None:
        r = self._c.execute(
            "SELECT * FROM custom_agents WHERE id=?", (agent_id,)).fetchone()
        return self._row_to_agent(r) if r else None

    def create(self, name: str, role: str = "", system_prompt: str = "",
               tools: list[str] | None = None,
               recall_sources: list[str] | None = None) -> Agent:
        name = (name or "").strip() or "New Agent"
        base = _slug(name)
        aid, n = base, 2
        while self._c.execute("SELECT 1 FROM custom_agents WHERE id=?",
                              (aid,)).fetchone():
            aid = f"{base}-{n}"; n += 1
        # default toolset if none chosen
        tools = tools or ["search_brain", "remember", "list_entities", "web_search"]
        self._c.execute(
            "INSERT INTO custom_agents (id,name,role,system_prompt,tools,"
            "recall_sources,created_at) VALUES (?,?,?,?,?,?,?)",
            (aid, name, role, system_prompt, json.dumps(tools),
             json.dumps(recall_sources or []),
             datetime.now(timezone.utc).isoformat()))
        self._c.commit()
        return self.get(aid)

    def delete(self, agent_id: str) -> bool:
        try:
            from .agent_models import clear_agent_model
            clear_agent_model(agent_id)
        except Exception:
            pass
        cur = self._c.execute("DELETE FROM custom_agents WHERE id=?", (agent_id,))
        self._c.commit()
        return cur.rowcount > 0


_store = None


def get_custom_store() -> CustomAgentStore:
    global _store
    if _store is None:
        _store = CustomAgentStore()
    return _store
