"""What the agent does with a deeper budget — and what stops it running away.

The loop used to be five rounds, one tool at a time. Raising the ceiling is the
easy half; the hard half is that a model with twenty rounds and nothing new to
learn will spend them re-asking the same question. These tests cover both.
"""
import time

import pytest
from agent_harness import RecordingTool, ScriptedProvider

from chitragupta.agents import runtime
from chitragupta.agents.effort import get_effort
from chitragupta.agents.loop import ToolRunner, call_key
from chitragupta.models.base import ToolCall


@pytest.fixture
def scripted(monkeypatch):
    """Install a scripted provider and return a factory for it."""
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr("chitragupta.agents.runtime.get_provider",
                            lambda p, m: provider)
        monkeypatch.setattr("chitragupta.agents.runtime.resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


@pytest.fixture
def tool(monkeypatch):
    """Replace one real tool with a recording stand-in."""
    def install(name="list_entities", **kw):
        rec = RecordingTool(**kw)
        monkeypatch.setitem(runtime.__dict__.setdefault("_unused", {}), "x", None)
        from chitragupta.agents import tools as tools_mod
        monkeypatch.setitem(tools_mod.TOOL_IMPLS, name, rec)
        return rec
    return install


def _asks(name, n, **args):
    """A script of `n` rounds, each asking for the same tool."""
    return [[(name, args)] for _ in range(n)]


# ── depth ────────────────────────────────────────────────────────────────────

def test_low_effort_stops_early_and_high_effort_keeps_going(scripted, tool):
    """The gear selector has to actually change the gear.

    Asserted on tool rounds rather than provider calls: a turn also spends a
    model call on auto-learn, which is not part of the tool budget.
    """
    rec = tool()
    scripted([[("list_entities", {"limit": i})] for i in range(40)])
    low = runtime.run_turn("research", "dig", effort="low")

    rec2 = tool()
    scripted([[("list_entities", {"limit": i})] for i in range(40)])
    high = runtime.run_turn("research", "dig", effort="high")

    assert low.steps_used < high.steps_used, "high effort did not search deeper"
    assert low.steps_used <= get_effort("low").max_steps
    assert high.steps_used <= get_effort("high").max_steps
    assert rec.executions < rec2.executions


def test_the_old_five_step_ceiling_is_gone(scripted, tool):
    """The specific limit this work exists to remove."""
    tool()
    p = scripted([[("list_entities", {"limit": i})] for i in range(30)])
    runtime.run_turn("research", "dig", effort="high")
    assert p.rounds_used > 5


# ── not running away ─────────────────────────────────────────────────────────

def test_a_model_that_repeats_itself_is_asked_to_answer(scripted, tool):
    """The failure a deeper loop introduces: same call, same answer, forever."""
    rec = tool()
    p = scripted(_asks("list_entities", 30, limit=3))
    res = runtime.run_turn("research", "dig", effort="high")

    assert rec.executions == 1, "the identical call was executed more than once"
    assert p.rounds_used < 30, "the loop kept going after it stopped learning"
    assert res.reply, "the turn produced no answer"


def test_the_repeat_is_answered_from_memory_with_a_nudge(scripted, tool):
    rec = tool()
    p = scripted(_asks("list_entities", 4, limit=3))
    res = runtime.run_turn("research", "dig", effort="high")
    repeats = [s for s in res.trace if s.kind == "tool_result" and s.repeated]
    assert repeats, "no repeat was recorded in the trace"
    assert "already ran this exact call" in repeats[0].result
    assert rec.executions == 1


def test_spending_the_whole_budget_still_produces_an_answer(scripted, tool):
    """An agent that researched for twenty rounds can usually answer — it has
    just never been told to stop. It must not return the old placeholder."""
    tool()
    p = scripted([[("list_entities", {"limit": i})] for i in range(100)],
                 final_answer="here is what I found")
    res = runtime.run_turn("research", "dig", effort="high")
    assert res.reply == "here is what I found"
    assert "max tool steps" not in res.reply
    # The last call must have had tools withheld, or it would just ask again.
    assert p.tools_offered[-1] == []


# ── parallelism ──────────────────────────────────────────────────────────────

def test_independent_tool_calls_overlap(scripted, tool):
    """Two searches that have nothing to do with each other should not cost two
    round trips."""
    rec = tool(delay=0.25)
    scripted([[("list_entities", {"limit": 1}), ("list_entities", {"limit": 2}),
               ("list_entities", {"limit": 3})], "done"])
    started = time.perf_counter()
    runtime.run_turn("research", "dig", effort="high")
    elapsed = time.perf_counter() - started

    assert rec.executions == 3
    assert rec.peak_live > 1, "the calls ran one after another"
    assert elapsed < 0.25 * 3, f"no overlap: {elapsed:.2f}s for three 0.25s calls"


def test_low_effort_limits_how_many_run_at_once():
    """Parallelism is part of the budget, not a free win."""
    rec = RecordingTool(delay=0.15)
    from chitragupta.agents import tools as tools_mod
    original = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = rec
    try:
        runner = ToolRunner(effort=get_effort("low"))     # max_parallel_tools = 2
        runner.run([ToolCall(id=str(i), name="list_entities", arguments={"limit": i})
                    for i in range(6)])
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = original
    assert rec.executions == 6
    assert rec.peak_live <= get_effort("low").max_parallel_tools


def test_duplicate_calls_in_one_round_execute_once():
    """A model asking for the same thing three times in one breath is wasteful,
    not circling — run it once, answer all three."""
    rec = RecordingTool()
    from chitragupta.agents import tools as tools_mod
    original = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = rec
    try:
        runner = ToolRunner(effort=get_effort("high"))
        out = runner.run([ToolCall(id=str(i), name="list_entities",
                                   arguments={"limit": 3}) for i in range(3)])
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = original
    assert rec.executions == 1
    assert len({o.output for o in out}) == 1
    assert not runner.round_was_all_repeats(out), "one round of duplicates is not a stall"


def test_argument_order_does_not_hide_a_repeat():
    assert (call_key("search_brain", {"query": "x", "limit": 5})
            == call_key("search_brain", {"limit": 5, "query": "x"}))


# ── the result reports what it did ───────────────────────────────────────────

def test_the_turn_reports_its_effort_and_depth(scripted, tool):
    tool()
    scripted([[("list_entities", {"limit": 1})], [("list_entities", {"limit": 2})],
              "done"])
    res = runtime.run_turn("research", "dig", effort="medium")
    assert res.effort == "medium"
    assert res.steps_used == 2
    assert res.as_dict()["steps_used"] == 2
