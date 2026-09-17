"""A tool says whether it worked; the loop stops guessing from the text.

The loop used to match the start of a tool's output against a prefix list. It
got the three failures that actually happen wrong — a connector that is down, a
search that threw, a sync that errored all read as success — and it invented a
failure for any output beginning "Tool". So the model re-issued the same broken
call, read the memo's cached answer, and burned the stall counter instead of
trying something else.
"""
from __future__ import annotations

from chitragupta.agents.effort import get_effort
from chitragupta.agents.loop import ToolRunner
from chitragupta.agents.results import ToolResult, worked
from chitragupta.agents.tools import run_tool
from chitragupta.models.base import ToolCall


def test_a_tool_result_is_still_a_string():
    """Additive: every call site that treated it as one keeps working."""
    r = ToolResult("Roadmap Q3", ok=True)
    assert isinstance(r, str)
    assert r == "Roadmap Q3"
    assert "Roadmap" in r
    assert r.upper() == "ROADMAP Q3"


def test_the_failures_that_actually_happen_are_reported_as_failures():
    """Each of these read as SUCCESS under the old prefix match."""
    assert not worked(ToolResult.failed("The web search did not go through: boom"))
    assert not worked(ToolResult.failed("Gmail is not connected: no credentials"))
    assert not run_tool("no_such_tool", {}).ok
    assert not run_tool("add_task", {"due": "tomorrow"}).ok      # missing title


def test_an_ordinary_answer_beginning_with_tool_is_not_a_failure():
    """The old list flagged anything starting "Tool " — including real output."""
    assert worked(ToolResult("Tool budget remaining: 4 rounds"))


def test_an_empty_answer_is_not_a_failure():
    """Nothing found is an answer. Repeating the call would not help."""
    out = run_tool("web_search", {"query": "zzz", "max_results": 1})
    if out == "No web results found.":
        assert out.ok, "an empty result was reported as a failure"


def test_a_plain_string_from_a_tool_still_means_it_worked():
    out = run_tool("list_entities", {"limit": 1})
    assert isinstance(out, ToolResult)
    assert out.ok


def test_the_repeat_note_does_not_launder_a_failure_into_a_success():
    """`str + str` would drop the verdict — the exact shape of the old bug."""
    from chitragupta.agents import tools as tools_mod

    saved = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: ToolResult.failed("it broke")
    try:
        runner = ToolRunner(effort=get_effort("high"))
        first = runner.run([ToolCall(id="a", name="list_entities", arguments={})])
        again = runner.run([ToolCall(id="b", name="list_entities", arguments={})])
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    assert not first[0].ok
    assert again[0].repeated, "the memo did not recognise the repeat"
    assert not again[0].ok, "the repeat note turned a failure into a success"
    assert "already ran this" in again[0].output


def test_a_round_that_failed_is_what_triggers_the_retry_nudge(monkeypatch):
    """End to end: the nudge follows the field, not the prose."""
    from agent_harness import ScriptedProvider

    from chitragupta.agents import runtime
    from chitragupta.agents import tools as tools_mod
    from chitragupta.agents.planning import RETRY_NUDGE

    saved = tools_mod.TOOL_IMPLS["list_entities"]
    # Phrased so no prefix in the old marker list would ever have matched it.
    tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: ToolResult.failed(
        "Gmail is not connected: no credentials")
    provider = ScriptedProvider(script=[[("list_entities", {})], "ok"])
    monkeypatch.setattr(runtime, "get_provider", lambda p, m: provider)
    monkeypatch.setattr(runtime, "resolve_usable_model", lambda p, m: (m or "x", None))
    try:
        runtime.run_turn("research", "check my mail")
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    nudged = any(RETRY_NUDGE in (m.content or "")
                 for round_ in provider.calls for m in round_)
    assert nudged, "a failed tool did not produce the retry nudge"
