"""Lodestone MCP bridge.

Exposes the local Lodestone brain (and tasks + web search) to any MCP-capable
client — Claude Code in your terminal, Claude Desktop, Cursor — over stdio.
This is an INTEGRATION, not the product: it lets an external Claude share the
exact same local brain the Lodestone workspace agents use, so your terminal
Claude "already knows you" too.

Register with Claude Code:
    claude mcp add lodestone -- <python> -m lodestone.mcp_server.server
(or run `lodestone mcp-install` to print the exact command).
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from ..brain import get_brain
from ..tasks import get_tasks

mcp = MCPServer("lodestone")


@mcp.tool()
def search_brain(query: str, limit: int = 8) -> str:
    """Search the user's personal Lodestone brain (their memories + a knowledge
    graph of their people, projects and tools). Call this FIRST for anything
    about the user, their work, projects, preferences, or past decisions."""
    res = get_brain().recall(query, limit=limit)
    return res["context"] or "No relevant context found in the user's brain."


@mcp.tool()
def remember(text: str, title: str | None = None) -> str:
    """Save a durable fact/preference about the user into their Lodestone brain,
    so future sessions (and the workspace agents) know it."""
    out = get_brain().ingest(text, source="agent", kind="fact", title=title)
    return (f"Remembered (+{out['memories']} memory, +{out['entities']} entities)."
            if out["memories"] else "Not stored (empty or already known).")


@mcp.tool()
def brain_stats() -> str:
    """Summarize the user's brain: memory count and knowledge-graph size."""
    return json.dumps(get_brain().stats(), indent=2)


@mcp.tool()
def list_tasks(when: str | None = None) -> str:
    """List the user's open tasks. `when` may be today | overdue | upcoming."""
    tasks = get_tasks().list(when=when)
    if not tasks:
        return f"No {when or 'open'} tasks."
    return "\n".join(
        f"- {t['title']}" + (f" (due {t['due']})" if t["due"] else "")
        for t in tasks
    )


@mcp.tool()
def add_task(title: str, due: str | None = None) -> str:
    """Add a task/reminder. `due` accepts today, tomorrow, a weekday, 'in N
    days', or YYYY-MM-DD (also parsed from the title)."""
    t = get_tasks().add(title, due)
    return f"Added: {t['title']}" + (f" (due {t['due']})" if t["due"] else "")


@mcp.tool()
def complete_task(task: str) -> str:
    """Mark a task done, by id prefix or part of its title."""
    done = get_tasks().complete(task)
    return f"Completed: {done['title']}" if done else f"No task matched '{task}'."


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
