"""The date we tell the model must not come back as a tool argument.

`run_turn` states the current date directly in front of the question so a small
model cannot miss it. A model then copies its own input into the arguments it
emits, and the note stops being a note: `brain.recall` runs `parse_date_range`
over `search_brain`'s query, finds the date we supplied, and filters the brain
down to items dated today — so every question asked on a quiet day answered
"nothing in the brain matches that date", with only the always-included
canonical block left. Asked who someone was, an agent replied with the user's
weight goal.

These cover the shape of the note, the strip, and — the one that matters — that
a real turn never lets it reach a tool.
"""
from __future__ import annotations

import pytest
from agent_harness import ScriptedProvider

from chitragupta.agents import grounding, runtime
from chitragupta.core.dateparse import parse_date_range

DATE_LINE = "Tuesday, September 15, 2026"


@pytest.fixture
def scripted(monkeypatch):
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr("chitragupta.agents.runtime.get_provider",
                            lambda p, m: provider)
        monkeypatch.setattr("chitragupta.agents.runtime.resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


def test_prefixed_states_the_date_in_front_of_the_question():
    out = grounding.prefixed(DATE_LINE, "who is divyansh")
    assert out.startswith("[Today is Tuesday, September 15, 2026.]")
    assert out.endswith("who is divyansh")


def test_strip_removes_the_note_this_layer_added():
    assert grounding.strip(grounding.prefixed(DATE_LINE, "who is divyansh")) \
        == "who is divyansh"


def test_strip_leaves_a_bracketed_line_that_is_not_ours():
    """A note further in was written by somebody else — an email, most likely."""
    quoted = "summarise this: [Today is the day we ship.] ..."
    assert grounding.strip(quoted) == quoted


def test_the_note_is_what_turns_a_question_into_a_date_filter():
    """The regression in one line: with the note, recall gets a date range."""
    question = "who is divyansh"
    assert parse_date_range(question) is None
    assert parse_date_range(grounding.prefixed(DATE_LINE, question)) is not None
    # …and stripping it puts the question back where it started.
    assert parse_date_range(grounding.strip(
        grounding.prefixed(DATE_LINE, question))) is None


def test_strip_arguments_only_touches_strings():
    args = {"query": grounding.prefixed(DATE_LINE, "x"), "limit": 6, "deep": True}
    assert grounding.strip_arguments(args) == {"query": "x", "limit": 6, "deep": True}


def test_a_turn_never_lets_the_note_reach_a_tool(scripted, monkeypatch):
    """The end-to-end case: a model that echoes its input, as real ones do.

    The mock provider ships exactly this behaviour — it copies the user turn
    into `search_brain`'s query — so this is not a hypothetical model.
    """
    from chitragupta.agents import tools as tools_mod

    captured: dict = {}

    def echoing_search(**kwargs):
        captured.update(kwargs)
        return "ctx"

    monkeypatch.setitem(tools_mod.TOOL_IMPLS, "search_brain", echoing_search)

    # The model asks for search_brain with its own input verbatim — note and all.
    echoed = grounding.prefixed(DATE_LINE, "who is divyansh")
    provider = scripted([[("search_brain", {"query": echoed})], "found them"])

    result = runtime.run_turn("research", "who is divyansh")

    assert provider.rounds_used >= 1
    assert captured, "search_brain was never executed"
    assert "[Today is" not in captured["query"], (
        f"the grounding note reached the tool: {captured['query']!r}")
    assert captured["query"] == "who is divyansh"

    # The trace the user watches shows the clean call too, not our bookkeeping.
    calls = [s for s in result.trace if s.kind == "tool_call"
             and s.name == "search_brain"]
    assert calls, "no search_brain call in the trace"
    assert "[Today is" not in calls[0].arguments.get("query", "")
