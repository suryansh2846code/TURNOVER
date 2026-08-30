"""The four built-in agents, mirroring Turnstone: Inbox, Launch, Research, Personal.

All share one Brain; each is scoped to a domain with its own tools and voice.
"""
from __future__ import annotations

from .agent import Agent

_BASE_TOOLS = ["search_brain", "remember", "list_entities", "web_search"]

PRESETS: dict[str, Agent] = {
    "inbox": Agent(
        id="inbox",
        name="Inbox",
        role="email & communications",
        system_prompt=(
            "You handle the user's email and messages. You draft replies, "
            "summarize threads, and surface what needs a response — always in the "
            "user's voice and aware of their commitments. Pull real messages with "
            "gmail_search when useful."
        ),
        tools=_BASE_TOOLS + ["gmail_search", "web_search"],
        recall_sources=["gmail", "gcal"],
    ),
    "launch": Agent(
        id="launch",
        name="Launch",
        role="go-to-market & shipping",
        system_prompt=(
            "You are the user's GTM / launch operator. You help plan launches, "
            "write announcements, landing copy and outreach, and track what ships "
            "when — grounded in the user's actual projects from the brain. Capture "
            "action items as tasks."
        ),
        tools=_BASE_TOOLS + ["web_search", "add_task", "list_tasks", "complete_task"],
    ),
    "research": Agent(
        id="research",
        name="Research",
        role="research & analysis",
        system_prompt=(
            "You are the user's research assistant. You investigate topics, "
            "compare options, and synthesize findings — combining the public web "
            "with what the user already knows in their brain. Cite sources."
        ),
        tools=_BASE_TOOLS + ["web_search"],
    ),
    "personal": Agent(
        id="personal",
        name="Personal",
        role="personal life & assistant",
        system_prompt=(
            "You are the user's personal chief of staff. You help with their "
            "personal life, schedule, reminders, tasks, notes and anything that "
            "doesn't belong to a work agent. When they mention something to do, "
            "add it as a task; when they ask what's on, list their tasks. Warm, "
            "discreet, and proactive."
        ),
        tools=_BASE_TOOLS + ["add_task", "list_tasks", "complete_task"],
    ),
}


def list_agents() -> list[Agent]:
    from .custom import get_custom_store
    return list(PRESETS.values()) + get_custom_store().list()


def get_agent(agent_id: str) -> Agent:
    if agent_id in PRESETS:
        return PRESETS[agent_id]
    from .custom import get_custom_store
    custom = get_custom_store().get(agent_id)
    if custom:
        return custom
    raise KeyError(f"unknown agent '{agent_id}'")
