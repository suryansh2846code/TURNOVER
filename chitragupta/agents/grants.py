"""What one agent has been granted, what it could have, and what it cannot.

A user connected Notion — signed in, twenty-five working tools — and asked their
agent to summarise a page. It answered out of Notion's *notification emails* and
said the connector was probably still syncing. One step, `search_brain`.

Nothing was broken. The agent had been built before Notion was connected, its
stored tools carried no `mcp` sentinel, and `mcp_tools.describe()` returns `[]`
when nothing is connected — so the option did not exist to tick at build time,
and nothing ever told anyone to go back.

The missing thing was this view. `describe_tools()` answers *what exists*; this
answers *what does this agent have*, and the second is not a filter over the
first — it needs the agent, how the sentinel resolves right now, and whether the
connector behind a tool is actually answering.

Contract, including every field name: `docs/development/agent-tool-grants.md`.
"""
from __future__ import annotations

from typing import Any

from ..log import get_logger, suppressed
from .mcp_tools import SENTINEL

log = get_logger(__name__)

#: Shown for the sentinel when the user has no connectors yet. Granting a
#: standing permission before there is anything behind it is a real choice, and
#: the row says so rather than pretending the category does not exist — hiding
#: it is what produced the bug this module exists for.
NOTHING_CONNECTED = ("No connectors are set up yet. Granting this now covers "
                     "them as soon as there are.")



def _mcp_rows() -> list[dict[str, str]]:
    """The connector tool rows, without the sentinel `describe()` prepends."""
    from . import mcp_tools

    return [r for r in mcp_tools.describe() if r.get("name") != SENTINEL]


def _configured_connectors() -> list[tuple[str, Any]]:
    """(display label, spec) for every connector the user has set up.

    Imported by name at call time, the way `mcp_tools` does: a checkout without
    the connector layer has no connectors, which is "nothing to show" and not a
    broken endpoint.
    """
    out: list[tuple[str, Any]] = []
    with suppressed("listing the user's connectors for the agent tool view"):
        from ..connectors.mcp_source import list_servers

        for spec in list_servers():
            label = (getattr(spec, "name", "") or getattr(spec, "id", "")
                     or "a connector")
            out.append((str(label), spec))
    return out


def _why_silent(spec: Any, label: str) -> str:
    """Why this connector is contributing no tools, in the user's terms.

    Only reached for a connector that is already failing — a working one
    produces tools and is never probed. So the probe is paid exactly when its
    answer is the thing the user needs.
    """
    with suppressed("asking a connector why it is not answering"):
        from ..connectors.mcp_source import MCPConnector

        ready, reason, _can_sync = MCPConnector(spec).status()
        if ready:
            # Answering, but exposing nothing readable. Saying "signed out"
            # here would be a guess, and a wrong one.
            return (f"{label} is connected but is not offering anything an "
                    "agent can read.")
        if reason:
            return str(reason)
    return f"{label} is not answering just now — check it under Connectors."


def _rows_for(agent: Any, *, include_unavailable: bool = True) -> list[dict[str, str]]:
    from .tools import TOOL_DEFS

    stored = list(getattr(agent, "tools", []) or [])
    held = set(stored)
    has_category = SENTINEL in held

    rows: list[dict[str, str]] = []

    # ── the built-ins ────────────────────────────────────────────────────
    for name, tool in TOOL_DEFS.items():
        rows.append({
            "name": name,
            "label": name,
            "description": tool.description,
            "source": "builtin",
            "connector": "",
            "state": "granted" if name in held else "available",
            "via": "direct" if name in held else "",
            "reason": "",
        })

    # ── the category ─────────────────────────────────────────────────────
    connector_rows = _mcp_rows()
    rows.append({
        "name": SENTINEL,
        # `name` is the stored value; `label` is the only part a person reads.
        # Rendering the name put the protocol's acronym on screen as a skill.
        "label": "Everything my connectors can read",
        "description": ("Everything the user's connectors can read. Stays "
                        "correct as connectors are added or removed."),
        "source": "category",
        "connector": "",
        "state": "granted" if has_category else "available",
        "via": "direct" if has_category else "",
        "reason": "" if connector_rows else NOTHING_CONNECTED,
    })

    # ── one connector's tools at a time ──────────────────────────────────
    contributing: set[str] = set()
    for row in connector_rows:
        name = row.get("name", "")
        contributing.add(row.get("connector", ""))
        direct = name in held
        rows.append({
            **row,
            "state": "granted" if (direct or has_category) else "available",
            # A tool reached through the category is NOT in the stored list, so
            # a consumer must not offer to untick it — unticking the category is
            # the only thing that would do anything.
            "via": "direct" if direct else ("category" if has_category else ""),
            "reason": "",
        })

    # ── connectors that are contributing nothing ─────────────────────────
    if include_unavailable:
        for label, spec in _configured_connectors():
            if label in contributing:
                continue
            rows.append({
                # Empty because there is nothing to grant — which is the point
                # of the row, not an omission.
                "name": "",
                "label": label,
                "description": "",
                "source": "mcp",
                "connector": label,
                "state": "unavailable",
                "via": "",
                "reason": _why_silent(spec, label),
            })

    return rows


def reaches_connectors(agent: Any) -> bool:
    """Can this agent reach anything the user's connectors expose?"""
    stored = set(getattr(agent, "tools", []) or [])
    if SENTINEL in stored:
        return True
    return any(r.get("name") in stored for r in _mcp_rows())


def is_custom(agent_id: str) -> bool:
    """Did the user build this one, or does it ship with Chitragupta?

    Not a statement about whether it can be changed — everything can, because a
    change is recorded as an override. This is only about where the agent came
    from, which is what decides whether deleting it is a thing that makes sense.
    """
    from .presets import PRESETS

    return agent_id not in PRESETS


def default_tools(agent_id: str) -> list[str]:
    """What this agent would have if the user had never changed anything.

    A preset's shipped list, or a custom agent's list as it was built. Reported
    so the UI can offer "reset to default" and show what has been changed —
    which is only answerable because a change is recorded as an override rather
    than written over the original.
    """
    from .custom import get_custom_store
    from .presets import PRESETS

    if agent_id in PRESETS:
        return list(PRESETS[agent_id].tools)
    raw = get_custom_store().get(agent_id)
    return list(raw.tools) if raw else []


def is_overridden(agent_id: str) -> bool:
    """Has the user changed this agent's tools from its default?"""
    from .tool_overrides import get_tool_overrides

    return get_tool_overrides().get(agent_id) is not None


def for_agent(agent_id: str) -> dict[str, Any]:
    """The whole per-agent view. Raises KeyError if there is no such agent."""
    from .presets import get_agent

    agent = get_agent(agent_id)
    rows = _rows_for(agent)
    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "custom": is_custom(agent_id),
        # Every agent is editable — a change is recorded as an override, so a
        # preset keeps its shipped definition and can still be improved later.
        "overridden": is_overridden(agent_id),
        "default_tools": default_tools(agent_id),
        "reaches_connectors": reaches_connectors(agent),
        "connector_tool_count": len(_mcp_rows()),
        "tools": rows,
    }


def connector_gaps() -> dict[str, Any]:
    """Which of the user's agents cannot reach the connectors they have.

    Reads. Never grants — connector access is a permission the user set, and an
    agent that already exists was configured by somebody who did not tick this
    box. Quietly ticking it later because we shipped a feature would be changing
    something while surfacing nothing.
    """
    from .presets import list_agents

    rows = _mcp_rows()
    if not rows:
        return {"connectors": [], "tool_count": 0, "agents": []}

    connectors = sorted({r.get("connector", "") for r in rows if r.get("connector")})
    missing = []
    for agent in list_agents():
        if reaches_connectors(agent):
            continue
        missing.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "custom": is_custom(agent.id),
        })
    return {"connectors": connectors, "tool_count": len(rows), "agents": missing}


