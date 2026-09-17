"""Every model call is counted, whichever way it was made.

`_wrap_usage` used to wrap `chat()` and call itself the choke point. It was not:
the agent loop calls `stream()`, and every provider that really streams
overrides `stream()` and never touches `chat()`. So the biggest spender in the
app recorded nothing, while the subscription paths that fall back to `chat()`
recorded normally — a meter that was wrong, and wrong differently for two users
of the same app.

The other half of the risk is counting twice: a provider with no real streaming
answers `stream()` by calling its own `chat()`, so one result reaches both
wrappers.
"""
from __future__ import annotations

import pytest

from chitragupta.models.base import ChatResult, LLMProvider
from chitragupta.models.registry import _wrap_usage


class _Recorder:
    """Stands in for `usage.record`, counting what reaches it."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, provider, model, tin, tout, calls=1):
        self.calls.append((provider, model, tin, tout))


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    import chitragupta.usage
    monkeypatch.setattr(chitragupta.usage, "record", rec)
    return rec


class _DelegatingProvider(LLMProvider):
    """No real streaming — `stream()` falls through to `chat()`, as the base
    implementation and the two subscription paths do."""

    name = "delegating"
    model = "d-1"

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        return ChatResult(text="hello", input_tokens=11, output_tokens=7)


class _RealStreamProvider(LLMProvider):
    """Real streaming — `chat()` is never called, which is the case that was
    silently uncounted for every API-key user."""

    name = "realstream"
    model = "r-1"

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        raise AssertionError("chat() must not be called on the streaming path")

    def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        from chitragupta.models.streaming import StreamEvent
        yield StreamEvent("text", "hel")
        yield StreamEvent("text", "lo")
        yield StreamEvent("done", result=ChatResult(
            text="hello", input_tokens=13, output_tokens=5))


def _drain(provider):
    return list(provider.stream([], tools=None))


def test_a_streaming_turn_is_counted(recorder):
    p = _RealStreamProvider()
    _wrap_usage(p)
    _drain(p)
    assert recorder.calls == [("realstream", "r-1", 13, 5)], (
        "a real streaming provider recorded nothing — the original bug")


def test_a_delegating_stream_is_counted_once_not_twice(recorder):
    """One result reaches both wrappers; it must be counted once."""
    p = _DelegatingProvider()
    _wrap_usage(p)
    _drain(p)
    assert len(recorder.calls) == 1, f"counted {len(recorder.calls)}x"
    assert recorder.calls[0] == ("delegating", "d-1", 11, 7)


def test_plain_chat_is_still_counted(recorder):
    """The paths that always worked — enrichment, digest, welcome — keep working."""
    p = _DelegatingProvider()
    _wrap_usage(p)
    p.chat([])
    assert recorder.calls == [("delegating", "d-1", 11, 7)]


def test_a_stream_that_never_finishes_still_counts_what_it_spent(recorder):
    """A stopped turn spent real tokens before it was stopped."""
    class _Halfway(LLMProvider):
        name = "halfway"
        model = "h-1"

        def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
            from chitragupta.models.streaming import StreamEvent
            yield StreamEvent("text", "partial answer")
            # no done event — the turn was stopped

    p = _Halfway()
    _wrap_usage(p)
    _drain(p)
    assert len(recorder.calls) == 1
    assert recorder.calls[0][3] > 0, "the partial output was not counted"


def test_the_turn_reports_what_it_spent(monkeypatch):
    """The number reaches TurnResult, so effort can be argued with."""
    from agent_harness import ScriptedProvider

    from chitragupta.agents import runtime

    class _Costed(ScriptedProvider):
        def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
            result = super().chat(messages, tools=tools, temperature=temperature,
                                  max_tokens=max_tokens)
            result.input_tokens, result.output_tokens = 100, 20
            return result

    provider = _Costed(script=[[("list_entities", {"limit": 1})], "done"])
    monkeypatch.setattr(runtime, "get_provider", lambda p, m: provider)
    monkeypatch.setattr(runtime, "resolve_usable_model", lambda p, m: (m or "x", None))

    result = runtime.run_turn("research", "hello")

    assert result.tokens_in >= 100, f"turn reported {result.tokens_in} input tokens"
    assert result.tokens_out >= 20
    assert result.as_dict()["tokens_in"] == result.tokens_in
