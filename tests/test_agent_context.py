"""What an agent remembers of the conversation.

The window was six messages. The comment justifying it was right about the
symptom — long histories confuse small models and let stale turns bleed into
unrelated answers — and wrong about the cure: the answer to "too much history"
is to compress the old part, not delete it. An assistant sold as a chief of
staff that has forgotten what you said four messages ago is not one.
"""
import pytest
from agent_harness import ScriptedProvider

from chitragupta.agents import runtime
from chitragupta.agents.agent import AgentMemory
from chitragupta.agents.context import MIN_TO_COMPACT, build_history
from chitragupta.agents.effort import get_effort
from chitragupta.agents.presets import get_agent


@pytest.fixture
def mem():
    m = AgentMemory()
    m.clear("research")
    yield m
    m.clear("research")


def _converse(mem, n, start=0):
    for i in range(start, start + n):
        mem.append("research", "user", f"Point number {i} about the harbour plan")
        mem.append("research", "assistant", f"Noted point {i}.")


def test_a_short_conversation_is_kept_word_for_word(mem):
    _converse(mem, 2)
    msgs = build_history(mem, get_agent("research"), get_effort("medium"))
    assert all(m.role in ("user", "assistant") for m in msgs), "nothing to summarise yet"
    assert any("Point number 0" in m.content for m in msgs)


def test_old_turns_are_summarised_rather_than_forgotten(mem):
    """The whole point. Turn 0 is far outside any verbatim window, and the agent
    still knows it happened."""
    _converse(mem, 30)
    effort = get_effort("low")            # heuristic writer, no model needed
    msgs = build_history(mem, get_agent("research"), effort)

    summary = [m for m in msgs if m.role == "system"]
    assert summary, "everything older than the window was simply dropped"
    assert "harbour plan" in summary[0].content
    verbatim = [m for m in msgs if m.role != "system"]
    assert len(verbatim) <= effort.history_verbatim


def test_the_window_follows_the_effort_setting(mem):
    _converse(mem, 30)
    agent = get_agent("research")
    low = [m for m in build_history(mem, agent, get_effort("low")) if m.role != "system"]
    high = [m for m in build_history(mem, agent, get_effort("high")) if m.role != "system"]
    assert len(high) > len(low)


def test_the_summary_is_extended_not_rewritten_from_scratch(mem):
    """A long conversation must not re-summarise itself on every message. Only
    the slice that has newly aged out is folded in."""
    _converse(mem, 30)
    effort = get_effort("medium")
    provider = ScriptedProvider(script=[], final_answer="They are planning a harbour.")
    build_history(mem, get_agent("research"), effort, provider)
    first_calls = len(provider.calls)
    assert first_calls == 1, "the summary was not written"

    stored = mem.get_summary("research")
    assert stored and stored["through_ts"]

    # Nothing new has aged out: no second call.
    build_history(mem, get_agent("research"), effort, provider)
    assert len(provider.calls) == first_calls, "it re-summarised with nothing new"

    # Enough new turns to push more out of the window: one more call, and it is
    # given the previous summary to build on rather than the whole transcript.
    _converse(mem, MIN_TO_COMPACT + effort.history_verbatim, start=100)
    build_history(mem, get_agent("research"), effort, provider)
    assert len(provider.calls) == first_calls + 1
    folded = provider.calls[-1][-1].content
    assert "Existing summary:" in folded
    assert "They are planning a harbour." in folded


def test_low_effort_never_spends_a_model_call_on_summarising(mem):
    """A small local model should not pay for a summary before it has even read
    the question."""
    _converse(mem, 30)
    provider = ScriptedProvider(script=[])
    build_history(mem, get_agent("research"), get_effort("low"), provider)
    assert provider.calls == [], "low effort called the model to summarise"


def test_a_failed_summary_call_falls_back_instead_of_losing_the_turn(mem):
    """The summary is a convenience; it must never be able to break a turn."""
    class Broken(ScriptedProvider):
        def chat(self, *a, **kw):
            raise RuntimeError("model down")

    _converse(mem, 30)
    msgs = build_history(mem, get_agent("research"), get_effort("high"), Broken())
    assert [m for m in msgs if m.role == "system"], "no fallback summary was written"


def test_clearing_an_agent_forgets_its_summary_too(mem):
    _converse(mem, 30)
    build_history(mem, get_agent("research"), get_effort("low"))
    assert mem.get_summary("research")
    mem.clear("research")
    assert mem.get_summary("research") is None, "clear left the old summary behind"


def test_a_real_turn_carries_the_summary(monkeypatch, mem):
    """End to end: the compacted history reaches the model."""
    _converse(mem, 30)
    provider = ScriptedProvider(script=["ok"])
    monkeypatch.setattr("chitragupta.agents.runtime.get_provider", lambda p, m: provider)
    monkeypatch.setattr("chitragupta.agents.runtime.resolve_usable_model",
                        lambda p, m: (m or "scripted-1", None))
    runtime.run_turn("research", "what were we discussing?", effort="low")
    sent = "\n".join(m.content for m in provider.calls[0] if m.role == "system")
    assert "Earlier in this conversation" in sent
