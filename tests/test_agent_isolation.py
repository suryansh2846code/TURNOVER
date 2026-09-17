"""An agent's conversation is its own, and agents talk by asking, not by sharing.

Asking Inbox something that it passed to Research used to put a message into the
user's Research chat that they never typed — and then fold it into that agent's
running summary, so one delegated question permanently distorted a conversation
happening somewhere else. Isolation is the fix; messaging is what replaces it.
"""
from __future__ import annotations

import pytest
from agent_harness import ScriptedProvider

from chitragupta.agents import runtime
from chitragupta.agents.agent import AgentMemory
from chitragupta.agents.tools import MAX_PARALLEL_AGENTS, run_tool


@pytest.fixture
def scripted(monkeypatch):
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr(runtime, "get_provider", lambda p, m: provider)
        monkeypatch.setattr(runtime, "resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


def _history_len(agent_id: str) -> int:
    return len(AgentMemory().history(agent_id, limit=500))


def test_a_delegated_question_stays_out_of_the_other_agents_chat(scripted):
    before = _history_len("research")
    scripted([], final_answer="research says hello")

    out = run_tool("ask_agent", {"agent_id": "research",
                                 "question": "what do you know about vendors?"})

    assert out.ok
    assert "research says hello" in out
    assert _history_len("research") == before, (
        "a delegated question was written into the user's Research chat")


def test_the_users_own_turn_is_still_remembered(scripted):
    """Isolation is for delegation only — a real conversation still persists."""
    before = _history_len("research")
    scripted([], final_answer="noted")

    runtime.run_turn("research", "remember I prefer short answers")

    assert _history_len("research") == before + 2, "the user's own turn was dropped"


def test_an_isolated_turn_does_not_read_the_other_agents_history(scripted):
    """One self-contained question, not a continuation of someone else's chat.

    The marker is deliberately not self-disclosure: the shared brain is shared
    on purpose, so a phrase that auto-learn would ingest would show up through
    recall and prove nothing about the conversation window.
    """
    marker = "ZZQX-CONVERSATION-MARKER"
    scripted([], final_answer="ok")
    runtime.run_turn("personal", f"the codeword is {marker}")   # seed a chat

    # It really is in that agent's own history…
    assert any(marker in (r["content"] or "")
               for r in AgentMemory().history("personal", limit=20))

    provider = scripted([], final_answer="answered")
    runtime.run_turn("personal", "unrelated question", persist=False)

    sent = provider.calls[0]
    assert not any(marker in (m.content or "") for m in sent), (
        "an isolated turn was handed the agent's own conversation")


# ── messaging ────────────────────────────────────────────────────────────
def test_several_agents_can_be_asked_at_once(scripted):
    scripted([], final_answer="an answer")

    out = run_tool("ask_agents", {"questions": [
        {"agent_id": "research", "question": "vendor prices?"},
        {"agent_id": "personal", "question": "am I free Thursday?"},
    ]})

    assert out.ok
    assert out.count("answered") >= 2, f"expected two answers, got: {out[:200]}"


def test_asking_the_same_agent_twice_in_one_fan_out_asks_it_once(scripted):
    scripted([], final_answer="an answer")
    out = run_tool("ask_agents", {"questions": [
        {"agent_id": "research", "question": "a"},
        {"agent_id": "research", "question": "b"},
    ]})
    assert out.count("[research answered") == 1


def test_a_fan_out_with_nothing_usable_is_a_failure_not_silence():
    out = run_tool("ask_agents", {"questions": []})
    assert not out.ok
    assert "agent_id" in out


def test_the_fan_out_is_bounded():
    assert MAX_PARALLEL_AGENTS <= 4, "a fan-out is whole turns, not tool calls"
