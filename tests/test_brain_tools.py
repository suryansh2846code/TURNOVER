"""The agents can address the brain, not just search across it.

Brain and Canonical expose about a dozen query methods between them; exactly one
— top_entities, as list_entities — was wired to a tool. So "who is X and what am
I working on with them" was a vector search that hoped, when the graph could
have answered it exactly. And an agent could add a fact about the user but never
fix a wrong one.
"""
from __future__ import annotations

import pytest

from lodestone.agents import brain_tools
from lodestone.agents.presets import PRESETS
from lodestone.agents.tools import TOOL_DEFS, TOOL_IMPLS, build_tools, run_tool
from lodestone.brain import get_brain


@pytest.fixture
def seeded():
    b = get_brain()
    b.ingest("Divyansh is my brother and he is studying architecture.",
             source="manual", kind="fact", title="divyansh")
    b.ingest("I work at Acme Corp as a staff engineer.",
             source="manual", kind="fact", title="job")
    return b


# ── who_is ───────────────────────────────────────────────────────────────
def test_who_is_answers_from_the_graph(seeded):
    out = run_tool("who_is", {"name": "Divyansh"})
    assert out.ok
    assert "Divyansh" in out


def test_who_is_does_not_describe_the_nearest_stranger():
    """match_entities returns its best guess however poor; describing it as the
    answer is worse than saying nobody by that name is known."""
    out = run_tool("who_is", {"name": "Zzyzx Nobody Qqq"})
    assert out.ok, "an unknown name was reported as a tool failure"
    assert "Nothing in the knowledge graph matches" in out, out[:200]


def test_who_is_needs_a_name():
    assert not run_tool("who_is", {"name": "  "}).ok


# ── the curated views ────────────────────────────────────────────────────
def test_the_curated_views_are_reachable(seeded):
    for area in ("all", "about_you", "people", "work"):
        out = run_tool("whats_true_about_me", {"area": area})
        assert isinstance(out, str)
        assert out.ok or "not available" in out


def test_the_timeline_is_reachable():
    out = run_tool("timeline", {"limit": 5})
    assert out.ok or "not available" in out


def test_the_timeline_limit_is_bounded():
    out = brain_tools.timeline(limit=100000)
    assert isinstance(out, str)
    out = brain_tools.timeline(limit="nonsense")
    assert isinstance(out, str)


# ── provenance ───────────────────────────────────────────────────────────
def test_an_agent_can_say_where_a_fact_came_from(seeded):
    out = run_tool("why_do_you_think_that", {"claim": "I work at Acme Corp"})
    assert out.ok
    assert "Acme" in out or "nothing" in out.lower()


def test_provenance_needs_a_claim():
    assert not run_tool("why_do_you_think_that", {"claim": ""}).ok


# ── correcting ───────────────────────────────────────────────────────────
def test_correcting_supersedes_rather_than_editing(seeded):
    """Claims are append-only; the tool is shaped so that cannot be broken."""
    out = run_tool("correct_fact", {
        "old": "I work at Acme Corp as a staff engineer",
        "new": "The user left Acme Corp in March and now works at Globex."})
    assert out.ok, out

    recalled = get_brain().recall("where does the user work", limit=8)
    text = recalled["context"]
    assert "Globex" in text, "the correction is not what gets recalled"


def test_correcting_something_the_brain_never_knew_does_not_overwrite_a_neighbour(seeded):
    """Recall always returns a nearest hit; acting on it would corrupt the brain."""
    out = run_tool("correct_fact", {
        "old": "the user is a competitive yodeller",
        "new": "The user has never yodelled competitively."})
    assert out.ok
    assert "new fact" in out, out
    # The unrelated memory it would have superseded is still intact.
    assert "Acme" in get_brain().recall("where does the user work", limit=5)["context"]


def test_forgetting_refuses_rather_than_retracting_the_nearest_thing(seeded):
    """Destroying the wrong memory is the mistake the user cannot see us make."""
    out = run_tool("forget_fact", {"fact": "my lifelong career as a yodeller"})
    assert "not retracted anything" in out or "have not" in out
    assert "Acme" in get_brain().recall("where does the user work", limit=5)["context"]


def test_correcting_needs_both_halves():
    assert not run_tool("correct_fact", {"old": "x", "new": ""}).ok
    assert not run_tool("correct_fact", {"old": "", "new": "y"}).ok


# ── forgetting is opt-in ─────────────────────────────────────────────────
def test_no_shipped_agent_can_forget_by_default():
    """"Forget everything about X" is a sentence an injection would write."""
    for agent in PRESETS.values():
        assert "forget_fact" not in agent.tools, (
            f"{agent.id} ships with forget_fact in its tool list")


def test_forgetting_still_works_when_a_user_grants_it(seeded):
    granted = build_tools(["forget_fact"], self_id="x")
    assert [t.name for t in granted] == ["forget_fact"]
    out = run_tool("forget_fact",
                   {"fact": "Divyansh is my brother studying architecture."})
    assert out.ok, out
    assert "Retracted" in out


# ── wiring ───────────────────────────────────────────────────────────────
def test_every_new_tool_is_declared_and_implemented():
    added = ["who_is", "whats_true_about_me", "timeline", "why_do_you_think_that",
             "check_for_contradictions", "correct_fact", "forget_fact"]
    for name in added:
        assert name in TOOL_DEFS, f"{name} has no schema"
        assert name in TOOL_IMPLS, f"{name} has no implementation"


def test_the_shipped_agents_actually_get_them():
    for agent in PRESETS.values():
        names = {t.name for t in build_tools(agent.tools, self_id=agent.id)}
        assert "who_is" in names, f"{agent.id} cannot look anyone up"
        assert "correct_fact" in names, f"{agent.id} cannot fix a wrong fact"
