"""The browser half of streaming.

Server-Sent Events are framed by a blank line, and a network chunk can split a
frame anywhere — including in the middle of the JSON. A reader that assumes one
chunk is one frame passes every hand test and drops tokens against a real
server, so these tests deliberately cut the stream in awkward places.

Executed in node against the real `streamTurn`, like the other frontend
harnesses: `node --check` cannot see any of this.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "lodestone" / "web" / "app.js"
HARNESS = ROOT / "tests" / "js" / "stream_turn.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to execute the frontend")


def run(chunks, ok=True) -> dict:
    proc = subprocess.run(["node", str(HARNESS), str(APP_JS)],
                          input=json.dumps({"chunks": chunks, "ok": ok}),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def frame(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def test_tokens_build_up_a_preview():
    out = run([frame({"type": "token", "text": "Hel"}),
               frame({"type": "token", "text": "lo"}),
               frame({"type": "done", "result": {"reply": "Hello", "trace": []}})])
    assert out["previews"] == ["Hel", "Hello"], "the preview did not accumulate"
    assert out["result"]["reply"] == "Hello"


def test_a_frame_split_across_chunks_is_not_lost():
    """The failure that only shows against a real server."""
    whole = frame({"type": "token", "text": "split"}) + frame(
        {"type": "done", "result": {"reply": "split", "trace": []}})
    cut = len(whole) // 3
    out = run([whole[:cut], whole[cut:cut * 2], whole[cut * 2:]])
    assert out["previews"] == ["split"]
    assert out["result"]["reply"] == "split"


def test_several_frames_in_one_chunk_are_all_read():
    burst = "".join(frame({"type": "token", "text": c}) for c in "abc")
    out = run([burst + frame({"type": "done", "result": {"reply": "abc", "trace": []}})])
    assert out["previews"] == ["a", "ab", "abc"]


def test_tool_activity_is_named_in_the_users_words():
    out = run([frame({"type": "tool_call", "name": "gmail_search", "arguments": {}}),
               frame({"type": "tool_call", "name": "some_new_tool", "arguments": {}}),
               frame({"type": "done", "result": {"reply": "ok", "trace": []}})])
    assert out["notes"][0] == "Reading your mail…"
    # A tool with no label must still read as English, not as an identifier.
    assert out["notes"][1] == "some new tool"


def test_the_next_plan_step_is_shown():
    out = run([frame({"type": "plan", "steps": [
                   {"text": "Find the vendors", "done": True},
                   {"text": "Compare their prices", "done": False}]}),
               frame({"type": "done", "result": {"reply": "ok", "trace": []}})])
    assert out["notes"] == ["Compare their prices"]


def test_a_streamed_error_is_raised_not_swallowed():
    out = run([frame({"type": "error", "message": "unknown agent 'nobody'"})])
    assert out["result"] is None
    assert "nobody" in out["error"]


def test_malformed_frames_are_skipped_rather_than_breaking_the_turn():
    out = run(["data: {not json}\n\n",
               frame({"type": "token", "text": "fine"}),
               frame({"type": "done", "result": {"reply": "fine", "trace": []}})])
    assert out["result"]["reply"] == "fine"
