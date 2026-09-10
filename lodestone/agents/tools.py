"""Tools available to agents.

Tools are the agent's hands: they read the shared brain, remember new facts,
search the web, and (via connectors) reach into live apps. Each returns a
string the model reads back. The set an agent gets is filtered by its role.
"""
from __future__ import annotations

import json

import httpx

from ..brain import get_brain
from ..models.base import Tool


# ── brain tools (shared by every agent) ──────────────────────────────────
def _search_brain(query: str, limit: int = 6) -> str:
    res = get_brain().recall(query, limit=limit)
    if not res["context"]:
        return "No relevant context found in the user's brain."
    return res["context"]


def _remember(text: str, title: str | None = None) -> str:
    out = get_brain().ingest(text, source="agent", kind="fact", title=title)
    return f"Stored to brain (+{out['memories']} memory, +{out['entities']} entities)."


def _list_entities(limit: int = 15) -> str:
    ents = get_brain().graph.top_entities(limit=limit)
    if not ents:
        return "The knowledge graph is empty."
    return "\n".join(f"- {e['name']} ({e['type']}, {e['mentions']}×)" for e in ents)


def _web_search(query: str, max_results: int = 5) -> str:
    """Real web search via DuckDuckGo (ddgs). Returns titles + snippets + links
    so the model can answer with current, external information and cite sources."""
    try:
        from ddgs import DDGS
    except ImportError:
        return "web_search unavailable (pip install ddgs)."
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as exc:
        return f"web_search failed: {exc}"
    if not results:
        return "No web results found."
    lines = []
    for r in results:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        href = (r.get("href") or "").strip()
        lines.append(f"- {title}: {body}\n  ({href})")
    return "\n".join(lines)


# ── connector tools (live app access) ─────────────────────────────────────
def _add_task(title: str, due: str | None = None) -> str:
    from ..tasks import get_tasks
    t = get_tasks().add(title, due)
    when = f" (due {t['due']})" if t["due"] else ""
    return f"Added task: {t['title']}{when}"


def _list_tasks(when: str | None = None) -> str:
    from ..tasks import get_tasks
    tasks = get_tasks().list(when=when)
    if not tasks:
        scope = when or "open"
        return f"No {scope} tasks."
    lines = []
    for t in tasks:
        due = f"  ·  due {t['due']}" if t["due"] else ""
        lines.append(f"- {t['title']}{due}  (id {t['id'][:6]})")
    return "\n".join(lines)


def _complete_task(task: str) -> str:
    from ..tasks import get_tasks
    done = get_tasks().complete(task)
    return f"Completed: {done['title']}" if done else f"No task matched '{task}'."


def _gmail_search(query: str = "newer_than:30d", max_results: int = 10) -> str:
    from ..connectors import get_connector
    conn = get_connector("gmail")
    ready, reason = conn.is_configured()
    if not ready:
        return f"Gmail not connected: {reason}"
    res = conn.sync(query=query, max_results=max_results, interactive=False)
    if res.errors:
        return f"Gmail error: {res.errors[0]}"
    return _search_brain(query)  # freshly ingested, now recall it


def _create_open_loop(description: str, due_at: str | None = None, related_project: str | None = None, priority: str = "medium") -> str:
    loop = get_brain().create_open_loop(description=description, due_at=due_at, related_project=related_project, priority=priority)
    due = f" (due {loop['due_at']})" if loop.get("due_at") else ""
    proj = f" [{loop['related_project']}]" if loop.get("related_project") else ""
    return f"Created open loop: {loop.get('description')}{proj}{due}"


def _list_open_loops(project: str | None = None) -> str:
    loops = get_brain().get_open_loops(status="open", related_project=project)
    if not loops:
        return "No open loops."
    lines = []
    for l in loops:
        due = f"  ·  due {l['due_at']}" if l.get("due_at") else ""
        proj = f"  [{l['related_project']}]" if l.get("related_project") else ""
        lines.append(f"- {l['description']}{proj}{due}  (id {l['id'][:6]})")
    return "\n".join(lines)


def _complete_open_loop(loop: str) -> str:
    b = get_brain()
    all_loops = b.get_open_loops(status="open")
    target = None
    for l in all_loops:
        if l["id"].startswith(loop) or loop.lower() in l["description"].lower():
            target = l
            break
    if not target:
        return f"No open loop matched '{loop}'."
    done = b.complete_open_loop(target["id"])
    return f"Completed open loop: {done.get('description')}" if done else f"Could not complete '{loop}'."


TOOL_IMPLS = {
    "search_brain": _search_brain,
    "remember": _remember,
    "list_entities": _list_entities,
    "web_search": _web_search,
    "gmail_search": _gmail_search,
    "add_task": _add_task,
    "list_tasks": _list_tasks,
    "complete_task": _complete_task,
    "create_open_loop": _create_open_loop,
    "list_open_loops": _list_open_loops,
    "complete_open_loop": _complete_open_loop,
}

TOOL_DEFS: dict[str, Tool] = {
    "search_brain": Tool(
        name="search_brain",
        description="Search the user's personal brain (memories + knowledge graph) "
                    "for relevant context. Call this FIRST for anything about the "
                    "user, their projects, people, preferences, or past work.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up"},
                "limit": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
    ),
    "remember": Tool(
        name="remember",
        description="Save a new durable fact/preference about the user into the brain.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["text"],
        },
    ),
    "list_entities": Tool(
        name="list_entities",
        description="List the most-referenced entities (people, projects, tools) "
                    "in the user's knowledge graph.",
        parameters={"type": "object", "properties": {
            "limit": {"type": "integer", "default": 15}}},
    ),
    "web_search": Tool(
        name="web_search",
        description="Search the live public internet for current or external "
                    "information the user's brain does NOT contain — news, "
                    "weather, prices, facts, docs, anything happening now. Use "
                    "this whenever search_brain has no relevant answer.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 5}},
            "required": ["query"]},
    ),
    "gmail_search": Tool(
        name="gmail_search",
        description="Search the user's Gmail (read-only) and pull matching "
                    "messages into context. Use for email-related tasks.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "max_results": {"type": "integer", "default": 10}}},
    ),
    "add_task": Tool(
        name="add_task",
        description="Add a task/to-do/reminder for the user. Use whenever they "
                    "ask to remember to do something or note a task.",
        parameters={"type": "object", "properties": {
            "title": {"type": "string", "description": "What to do"},
            "due": {"type": "string", "description": "Optional due date phrase: "
                    "today, tomorrow, monday, in 3 days, or YYYY-MM-DD"}},
            "required": ["title"]},
    ),
    "list_tasks": Tool(
        name="list_tasks",
        description="List the user's tasks. Use for 'what's on today?', 'my "
                    "to-dos', 'what am I behind on?'.",
        parameters={"type": "object", "properties": {
            "when": {"type": "string", "enum": ["today", "overdue", "upcoming"],
                     "description": "Optional filter; omit for all open tasks"}}},
    ),
    "complete_task": Tool(
        name="complete_task",
        description="Mark a task done, by id prefix or a bit of its title.",
        parameters={"type": "object", "properties": {
            "task": {"type": "string"}}, "required": ["task"]},
    ),
    "create_open_loop": Tool(
        name="create_open_loop",
        description="Track an unfinished commitment, pending follow-up, or open loop.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What needs follow-up or completion"},
                "due_at": {"type": "string", "description": "Optional deadline"},
                "related_project": {"type": "string", "description": "Optional project name"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "default": "medium"},
            },
            "required": ["description"],
        },
    ),
    "list_open_loops": Tool(
        name="list_open_loops",
        description="List active open loops and commitments.",
        parameters={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Filter by project name"},
            },
        },
    ),
    "complete_open_loop": Tool(
        name="complete_open_loop",
        description="Mark an open loop completed by id prefix or text.",
        parameters={
            "type": "object",
            "properties": {
                "loop": {"type": "string", "description": "Loop id or description text"},
            },
            "required": ["loop"],
        },
    ),
}


def build_tools(names: list[str]) -> list[Tool]:
    tools = []
    seen = set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        if n in TOOL_DEFS:
            t = TOOL_DEFS[n]
            tools.append(Tool(name=t.name, description=t.description,
                              parameters=t.parameters, handler=TOOL_IMPLS[n]))
    return tools


def run_tool(name: str, arguments: dict) -> str:
    impl = TOOL_IMPLS.get(name)
    if not impl:
        return f"Unknown tool: {name}"
    try:
        return impl(**arguments)
    except TypeError as exc:
        return f"Bad arguments for {name}: {exc}"
    except Exception as exc:
        return f"Tool {name} failed: {exc}"
