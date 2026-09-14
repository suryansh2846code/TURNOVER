"""Stop has to stop the work, not just stop watching it.

The button used to abort the browser's fetch and print "stopped" while the turn
carried on — up to twenty-one more model calls at High, then two more learning
from a conversation the user had walked away from, all on their own key. These
tests hold the line the screen was already claiming: after Stop, no further
model call, no further tool, and no post-turn curation.
"""
from __future__ import annotations

import threading

import pytest
from agent_harness import ScriptedProvider

from lodestone.agents import cancellation, runtime
from lodestone.agents.effort import get_effort
from lodestone.agents.loop import STOPPED_OUTPUT, ToolRunner
from lodestone.models.base import ToolCall


@pytest.fixture
def scripted(monkeypatch):
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr("lodestone.agents.runtime.get_provider",
                            lambda p, m: provider)
        monkeypatch.setattr("lodestone.agents.runtime.resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


# ── the registry ─────────────────────────────────────────────────────────
def test_cancel_before_the_turn_registers_is_not_lost():
    """The user can press Stop before the server has heard of the turn."""
    cancellation.cancel("early-turn")
    event = cancellation.begin("early-turn")
    assert cancellation.stopped(event), "a Stop that arrived first was discarded"
    cancellation.end("early-turn")


def test_stop_is_idempotent_and_a_turn_with_no_id_is_simply_not_stoppable():
    assert cancellation.cancel("twice") is True
    assert cancellation.cancel("twice") is True
    cancellation.end("twice")
    assert cancellation.begin(None) is None
    assert cancellation.stopped(None) is False


def test_the_registry_is_bounded():
    """A browser that goes away mid-turn never calls end()."""
    for i in range(cancellation.MAX_TRACKED * 2):
        cancellation.begin(f"leaked-{i}")
    assert cancellation.tracked() <= cancellation.MAX_TRACKED
    for i in range(cancellation.MAX_TRACKED * 2):
        cancellation.end(f"leaked-{i}")


# ── the loop ─────────────────────────────────────────────────────────────
def test_a_stopped_turn_makes_no_further_model_call(scripted):
    """The check that matters: everything after it is what the user pays for."""
    stop = threading.Event()
    calls = {"n": 0}

    def counting_tool(**kw):
        calls["n"] += 1
        stop.set()               # the user presses Stop during the first tool
        return "something"

    from lodestone.agents import tools as tools_mod
    saved = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = counting_tool
    try:
        provider = scripted([[("list_entities", {"limit": i})] for i in range(24)])
        result = runtime.run_turn("research", "dig deep", effort="high",
                                  cancel=stop)
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    assert result.stopped is True
    assert calls["n"] == 1, f"tools kept running after Stop: {calls['n']}"
    # One model call to ask for the tool. Anything more is spend after Stop.
    assert provider.rounds_used == 1, (
        f"{provider.rounds_used} model calls after Stop; expected 1")


def test_a_turn_stopped_before_it_starts_costs_nothing(scripted):
    stop = threading.Event()
    stop.set()
    provider = scripted([[("list_entities", {"limit": 1})], "done"])

    result = runtime.run_turn("research", "never mind", cancel=stop)

    assert result.stopped is True
    assert provider.rounds_used == 0, "a pre-stopped turn still called the model"
    # Not `trace == []`: auto-recall records a step before the loop begins, and
    # whether it finds anything depends on what is in the brain. What must be
    # empty is the work — no tool ran.
    assert [s for s in result.trace if s.kind == "tool_call"] == []


def test_the_half_written_answer_is_kept(scripted):
    """Stop must not cost the user the part they already paid for."""
    stop = threading.Event()

    class Halfway(ScriptedProvider):
        def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
            from lodestone.models.streaming import StreamEvent
            yield StreamEvent("text", "Here is what I foun")
            stop.set()                      # Stop lands mid-sentence
            yield StreamEvent("text", "d in your calendar…")

    provider = Halfway(script=[])
    import lodestone.agents.runtime as rt
    saved_get, saved_resolve = rt.get_provider, rt.resolve_usable_model
    rt.get_provider = lambda p, m: provider          # type: ignore[assignment]
    rt.resolve_usable_model = lambda p, m: (m or "x", None)  # type: ignore[assignment]
    try:
        result = runtime.run_turn("research", "what's on?", cancel=stop)
    finally:
        rt.get_provider, rt.resolve_usable_model = saved_get, saved_resolve

    assert result.stopped is True
    assert "Here is what I foun" in result.reply, "the partial answer was thrown away"
    assert runtime.STOPPED_NOTE in result.reply


def test_a_stopped_turn_does_not_curate_the_brain(scripted, monkeypatch):
    """The two post-turn model calls are exactly what Stop should prevent."""
    learned = {"n": 0}
    monkeypatch.setattr(runtime, "_auto_learn",
                        lambda *a, **k: learned.__setitem__("n", learned["n"] + 1) or 0)

    stop = threading.Event()
    stop.set()
    scripted([], final_answer="never runs")
    result = runtime.run_turn("research", "I work at Acme", cancel=stop)

    assert result.stopped is True
    assert learned["n"] == 0, "a stopped turn still spent a call learning"


# ── the tool runner ──────────────────────────────────────────────────────
def test_queued_tools_in_a_round_do_not_run_after_stop():
    """A round of six stopped after the first must not run the other five."""
    stop = threading.Event()
    ran = {"n": 0}

    from lodestone.agents import tools as tools_mod
    saved = tools_mod.TOOL_IMPLS["list_entities"]
    tools_mod.TOOL_IMPLS["list_entities"] = lambda **kw: ran.__setitem__(
        "n", ran["n"] + 1) or "ok"
    try:
        runner = ToolRunner(effort=get_effort("high"), cancel=stop)
        stop.set()
        outcomes = runner.run([
            ToolCall(id=f"c{i}", name="list_entities", arguments={"limit": i})
            for i in range(6)
        ])
    finally:
        tools_mod.TOOL_IMPLS["list_entities"] = saved

    assert ran["n"] == 0, f"{ran['n']} tools ran after Stop"
    assert all(o.output == STOPPED_OUTPUT for o in outcomes)


# ── delegation ───────────────────────────────────────────────────────────
def test_stopping_a_turn_stops_the_agent_it_delegated_to():
    """Otherwise Stop is the same lie, one level further in."""
    from lodestone.agents import delegation

    stop = threading.Event()
    token = delegation.enter("inbox", get_effort("high"), stop)
    try:
        assert delegation.current_chain().cancel is stop
        inner = delegation.enter("research", get_effort("medium"))
        try:
            # The child did not name an event, so it inherits the parent's.
            assert delegation.current_chain().cancel is stop
        finally:
            delegation.leave(inner)
    finally:
        delegation.leave(token)
