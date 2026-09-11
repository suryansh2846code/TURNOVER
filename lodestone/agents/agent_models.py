"""Per-agent model binding subsystem.

Persists user-assigned models and providers for each agent (Inbox, Launch,
Research, Personal, or custom agents) so users can say:
"I'm talking to this agent, and I want this model to power it."
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_model_configs (
    agent_id    TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    model       TEXT,
    updated_at  TEXT NOT NULL
);
"""


def _get_db() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def get_agent_model(agent_id: str) -> tuple[str | None, str | None]:
    """Return (provider, model) configured for the agent, or (None, None)."""
    conn = _get_db()
    row = conn.execute(
        "SELECT provider, model FROM agent_model_configs WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if row:
        return row["provider"], row["model"]
    return None, None


def set_agent_model(agent_id: str, provider: str, model: str | None = None) -> dict[str, Any]:
    """Persist a model and provider choice for an agent."""
    conn = _get_db()
    provider = provider.strip().lower()
    model = (model or "").strip() or None
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO agent_model_configs (agent_id, provider, model, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(agent_id) DO UPDATE SET
            provider = excluded.provider,
            model = excluded.model,
            updated_at = excluded.updated_at
        """,
        (agent_id, provider, model, now),
    )
    conn.commit()
    return {
        "agent_id": agent_id,
        "provider": provider,
        "model": model,
        "updated_at": now,
    }


def clear_agent_model(agent_id: str) -> bool:
    """Clear custom model binding so the agent inherits the global default."""
    conn = _get_db()
    cur = conn.execute("DELETE FROM agent_model_configs WHERE agent_id = ?", (agent_id,))
    conn.commit()
    return cur.rowcount > 0


def list_agent_models() -> dict[str, dict[str, Any]]:
    """Return a mapping of all customized agent model configs."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM agent_model_configs").fetchall()
    return {
        r["agent_id"]: {
            "provider": r["provider"],
            "model": r["model"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    }
