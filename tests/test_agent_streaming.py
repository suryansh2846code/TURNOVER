"""Words appearing as they are written, instead of a spinner.

Streaming is the thing people *feel* about an assistant, and its absence is why
`app.js` carries a list of invented "thinking" phrases and an estimated-seconds
countdown to fill the silence.

The design point these tests pin: there is **one** loop. Streaming is a callback
on the same `run_turn`, not a second implementation — which is the only way the
streamed turn and the plain one cannot drift apart.
"""
import json

import pytest
from agent_harness import ScriptedProvider
from fastapi.testclient import TestClient

from chitragupta.agents import runtime
from chitragupta.api.app import app
from chitragupta.models.base import ChatResult, ToolCall
from chitragupta.models.streaming import anthropic_events, from_result, openai_events, sse_payloads

client = TestClient(app)


# ── wire formats ─────────────────────────────────────────────────────────────

def test_anthropic_wire_yields_text_then_assembles_tool_calls():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Look"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "ing…"}},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "t1", "name": "search_brain"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"query"'}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": ':"docks"}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"output_tokens": 9}},
    ]
    out = list(anthropic_events(json.dumps(e) for e in events))
    assert "".join(e.text for e in out if e.kind == "text") == "Looking…"
    result = out[-1].result
    assert result.tool_calls[0].name == "search_brain"
    assert result.tool_calls[0].arguments == {"query": "docks"}
    assert (result.input_tokens, result.output_tokens) == (11, 9)


def test_the_claude_cli_nesting_is_understood():
    """Verified against the real CLI: it wraps the same events one level down."""
    out = list(anthropic_events([json.dumps(
        {"type": "stream_event",
         "event": {"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": "hi"}}})]))
    assert out[0].text == "hi"


def test_openai_wire_reassembles_interleaved_tool_arguments():
    """Two calls in one response interleave their argument chunks; `index` is
    what ties each one's fragments together."""
    chunks = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "a", "function": {"name": "add_task", "arguments": '{"ti'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 1, "id": "b", "function": {"name": "list_tasks", "arguments": "{"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'tle":"ship"}'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 1, "function": {"arguments": "}"}}]}}]},
        {"choices": [{"finish_reason": "tool_calls", "delta": {}}]},
    ]
    lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]
    result = list(openai_events(sse_payloads(lines)))[-1].result
    assert [c.name for c in result.tool_calls] == ["add_task", "list_tasks"]
    assert result.tool_calls[0].arguments == {"title": "ship"}


def test_malformed_tool_arguments_do_not_lose_the_call():
    """`run_tool` validates arguments and says what is wrong, which helps the
    model more than the call silently vanishing."""
    events = [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t", "name": "add_task"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"title": "trunc'}},
    ]
    result = list(anthropic_events(json.dumps(e) for e in events))[-1].result
    assert result.tool_calls and result.tool_calls[0].name == "add_task"


def test_sse_ignores_the_done_sentinel_and_blank_lines():
    assert list(sse_payloads(["", "event: ping", "data: {}", "data: [DONE]"])) == ["{}"]


# ── every provider streams ───────────────────────────────────────────────────

def test_every_registered_provider_can_stream():
    """The seam exists so callers never branch on whether a backend supports
    it. A provider that cannot really stream still yields a valid stream."""
    from chitragupta.models.registry import _REGISTRY

    for name, cls in _REGISTRY.items():
        assert hasattr(cls, "stream"), name


def test_the_fallback_is_a_valid_stream():
    result = ChatResult(text="all at once",
                        tool_calls=[ToolCall(id="1", name="x", arguments={})])
    out = list(from_result(result))
    assert out[0].kind == "text" and out[0].text == "all at once"
    assert out[-1].kind == "done" and out[-1].result is result


def test_the_offline_model_streams_so_the_path_can_be_exercised_with_no_keys():
    from chitragupta.models import get_provider
    from chitragupta.models.base import Message

    provider = get_provider("mock", "mock-1")
    out = list(provider.stream([Message(role="user", content="a b c d e f g h")]))
    text = [e for e in out if e.kind == "text"]
    assert len(text) > 1, "the offline model answered in one piece"
    assert "".join(e.text for e in text) == out[-1].result.text


# ── the turn ─────────────────────────────────────────────────────────────────

@pytest.fixture
def scripted(monkeypatch):
    def make(script, **kw):
        provider = ScriptedProvider(script=list(script), **kw)
        monkeypatch.setattr("chitragupta.agents.runtime.get_provider", lambda p, m: provider)
        monkeypatch.setattr("chitragupta.agents.runtime.resolve_usable_model",
                            lambda p, m: (m or "scripted-1", None))
        return provider
    return make


def test_a_turn_reports_tokens_tools_and_a_result(scripted, monkeypatch):
    from chitragupta.agents import tools as tools_mod

    monkeypatch.setitem(tools_mod.TOOL_IMPLS, "list_entities", lambda **kw: "two entities")
    scripted([[("list_entities", {"limit": 3})], "Here is the answer."])

    events = []
    result = runtime.run_turn("research", "dig", effort="medium",
                              on_event=events.append)

    kinds = [e["type"] for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds
    assert result.reply == "Here is the answer."
    # The scripted provider does not stream, so text arrives whole — the point
    # is that the callback fires either way.
    assert "".join(e.get("text", "") for e in events if e["type"] == "token")


def test_watching_a_turn_does_not_change_it(scripted, monkeypatch):
    """One loop, two viewings. If the streamed turn could differ from the plain
    one, every bug would need reproducing twice."""
    from chitragupta.agents import tools as tools_mod

    monkeypatch.setitem(tools_mod.TOOL_IMPLS, "list_entities", lambda **kw: "two")
    script = [[("list_entities", {"limit": 3})], "Same answer."]

    scripted(list(script))
    quiet = runtime.run_turn("research", "dig", effort="medium")
    scripted(list(script))
    watched = runtime.run_turn("research", "dig", effort="medium",
                               on_event=lambda _e: None)

    assert quiet.reply == watched.reply
    assert quiet.steps_used == watched.steps_used


# ── the endpoint ─────────────────────────────────────────────────────────────

def _read_stream(agent_id="research", **body):
    payload = {"message": "hello", "provider": "mock", "model": "mock-1", **body}
    with client.stream("POST", f"/api/agents/{agent_id}/chat/stream",
                       json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[5:]) for line in resp.iter_lines()
                if line.startswith("data:")]


def test_the_endpoint_streams_events_and_ends_with_one_done():
    events = _read_stream()
    assert events, "nothing was streamed"
    assert events[-1]["type"] == "done"
    assert [e["type"] for e in events].count("done") == 1
    assert events[-1]["result"]["reply"]


def test_the_streamed_text_previews_the_final_reply():
    """A client renders tokens as a preview and replaces them with `done` —
    so in the ordinary case the two must agree, or the reply visibly jumps."""
    events = _read_stream()
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed, "no tokens were streamed"
    assert events[-1]["result"]["reply"] == streamed


def test_an_unknown_agent_ends_the_stream_with_an_error_not_a_crash():
    events = _read_stream(agent_id="nobody")
    assert events[-1]["type"] == "error"
    assert "nobody" in events[-1]["message"]


def test_an_empty_message_is_refused_before_the_stream_opens():
    assert client.post("/api/agents/research/chat/stream",
                       json={"message": "   "}).status_code == 400
