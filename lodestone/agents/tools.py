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


def _web_search(query: str) -> str:
    """Lightweight web search via DuckDuckGo's instant-answer + HTML endpoint."""
    try:
        r = httpx.get(
            "https://duckduckgo.com/html/",
            params={"q": query}, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 Lodestone"},
        )
        import re
        snippets = re.findall(r'result__snippet[^>]*>(.*?)</a>', r.text)[:5]
        clean = [re.sub(r"<[^>]+>", "", s).strip() for s in snippets]
        clean = [c for c in clean if c]
        return "\n".join(f"- {c}" for c in clean) or "No web results."
    except Exception as exc:
        return f"web_search failed: {exc}"


# ── connector tools (live app access) ─────────────────────────────────────
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


TOOL_IMPLS = {
    "search_brain": _search_brain,
    "remember": _remember,
    "list_entities": _list_entities,
    "web_search": _web_search,
    "gmail_search": _gmail_search,
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
        description="Search the public web for current information.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]},
    ),
    "gmail_search": Tool(
        name="gmail_search",
        description="Search the user's Gmail (read-only) and pull matching "
                    "messages into context. Use for email-related tasks.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "max_results": {"type": "integer", "default": 10}}},
    ),
}


def build_tools(names: list[str]) -> list[Tool]:
    tools = []
    for n in names:
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
