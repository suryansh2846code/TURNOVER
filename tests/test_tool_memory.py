"""What a tool found survives the turn that found it.

Only the tool NAMES were stored; the outputs were discarded, and build_history
read nothing but user and assistant text. So "what was that third result again?"
sent the agent to search all over again — a fresh turn, so the memo is empty and
the user pays for it twice — or to reconstruct it from its own prose, which is
where invented detail comes from.
"""
from __future__ import annotations

import pytest
from agent_harness import ScriptedProvider

from chitragupta.agents import runtime
from chitragupta.agents.agent import AgentMemory
from chitragupta.agents.context import MAX_DIGEST_CALLS, MAX_DIGEST_CHARS, digest_of
from chitragupta.agents.runtime import TraceStep


@pytest.fixture
def scripted(monkeypatch):
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr(runtime, "get_provider", lambda p, m: provider)
        monkeypatch.setattr(runtime, "resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


def test_the_digest_pairs_each_call_with_what_it_returned():
    trace = [
        TraceStep(kind="tool_call", name="web_search", arguments={"query": "vendors"}),
        TraceStep(kind="tool_result", name="web_search", result="Acme, Globex, Initech"),
    ]
    out = digest_of(trace)
    assert out == [{"name": "web_search", "args": {"query": "vendors"},
                    "found": "Acme, Globex, Initech"}]


def test_a_long_result_is_cut_but_kept():
    trace = [
        TraceStep(kind="tool_call", name="search_brain", arguments={}),
        TraceStep(kind="tool_result", name="search_brain", result="x" * 5000),
    ]
    found = digest_of(trace)[0]["found"]
    assert len(found) == MAX_DIGEST_CHARS
    assert found


def test_a_turn_that_made_twenty_calls_does_not_remember_twenty():
    trace = []
    for i in range(20):
        trace.append(TraceStep(kind="tool_call", name="t", arguments={"i": i}))
        trace.append(TraceStep(kind="tool_result", name="t", result=f"r{i}"))
    assert len(digest_of(trace)) <= MAX_DIGEST_CALLS


def test_the_next_turn_is_told_what_the_last_one_found(scripted):
    from chitragupta.agents import tools as tools_mod

    saved = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: "Sokrates, Bellweather, Crane"
    try:
        scripted([[("list_entities", {"limit": 3})], "those three"])
        runtime.run_turn("writer", "who are the top entities?")

        provider = scripted([], final_answer="the third was Crane")
        runtime.run_turn("writer", "what was the third one again?")
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    sent = "\n".join((m.content or "") for m in provider.calls[0])
    assert "Crane" in sent, (
        "the next turn was not told what the previous turn's tools found")
    assert "list_entities" in sent


def test_the_stored_row_carries_the_result_not_only_the_name(scripted):
    from chitragupta.agents import tools as tools_mod

    saved = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: "a distinctive finding"
    try:
        scripted([[("list_entities", {})], "done"])
        runtime.run_turn("writer", "look something up")
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    rows = AgentMemory().history("writer", limit=4)
    stored = [r["tool_json"] for r in rows if r["tool_json"]]
    assert stored, "nothing was stored about the tools at all"
    assert "a distinctive finding" in stored[-1]


def test_rows_written_before_results_were_kept_do_not_break_anything():
    """Old rows hold a bare list of names. They must simply contribute nothing."""
    from chitragupta.agents.context import _tool_note

    assert _tool_note([{"tool_json": '["web_search", "search_brain"]'}]) == ""
    assert _tool_note([{"tool_json": "not json at all"}]) == ""
    assert _tool_note([]) == ""
