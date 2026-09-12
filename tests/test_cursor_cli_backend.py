"""Cursor runs through its CLI, not an HTTP API.

`api.cursor.com` carries Cursor's admin/agent surface but has no inference
route — verified 2026-09-12:

    GET  /v1/models            401  {"message":"Invalid User API Key"}
    POST /v1/chat/completions  404  {"message":"Route not found"}

So modelling Cursor as an OpenAI-compatible provider meant every message 404'd
regardless of the key, and "Sign in with Cursor" opened cursor.com/login and
learned nothing. Inference belongs to the headless CLI (`agent -p`).
"""
import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.models.base import Message, parse_cli_json
from lodestone.models.cursor import CursorProvider, find_cursor_cli

HELLO = [Message(role="user", content="hi")]
AGENT = "/Users/me/.local/bin/agent"


def _proc(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


# ── never speak HTTP to api.cursor.com ───────────────────────────────────
def test_cursor_never_posts_to_a_nonexistent_endpoint():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc('{"result":"hello"}')), \
         patch("httpx.post", side_effect=AssertionError("posted to api.cursor.com")):
        assert CursorProvider().chat(HELLO).text == "hello"


def test_an_api_key_alone_is_not_enough():
    """There is no endpoint a key could authenticate against."""
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=None):
        ready, reason = CursorProvider(api_key="cur-real-key").is_ready()
    assert ready is False
    assert "cursor.com/install" in reason


def test_missing_cli_explains_itself_instead_of_failing_silently():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=None):
        result = CursorProvider().chat(HELLO)
    assert "⚠️" in result.text and "agent" in result.text


# ── the CLI contract ─────────────────────────────────────────────────────
def test_headless_invocation_matches_the_documented_flags():
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env", {})
        return _proc('{"result":"ok"}')

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", side_effect=fake_run):
        CursorProvider(model="gpt-5", api_key="cur-key").chat(HELLO)

    cmd = seen["cmd"]
    assert cmd[0] == AGENT
    assert "-p" in cmd and "--output-format" in cmd and "json" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5"
    assert seen["env"]["CURSOR_API_KEY"] == "cur-key", "the CLI authenticates via env"


def test_system_context_is_folded_into_the_prompt():
    """`agent -p` wants an instruction, not a User:/Assistant: transcript."""
    seen = {}
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", side_effect=lambda cmd, **kw: (seen.setdefault("cmd", cmd),
                                                                _proc('{"result":"ok"}'))[1]):
        CursorProvider().chat([
            Message(role="system", content="You are terse."),
            Message(role="user", content="earlier"),
            Message(role="assistant", content="noted"),
            Message(role="user", content="now this"),
        ])
    prompt = seen["cmd"][seen["cmd"].index("-p") + 1]
    assert "You are terse." in prompt
    assert "now this" in prompt
    assert "Recent conversation so far" in prompt


def test_cli_failure_is_reported_readably():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc("", "not logged in", code=1)):
        result = CursorProvider().chat(HELLO)
    assert "not logged in" in result.text and "agent login" in result.text


def test_a_timeout_is_reported_not_raised():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired("agent", 180)):
        assert "timed out" in CursorProvider().chat(HELLO).text


def test_leading_cli_noise_does_not_break_parsing():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc('update available\n{"result":"hi"}')):
        assert CursorProvider().chat(HELLO).text == "hi"


# ── binary discovery must not grab a namesake ────────────────────────────
def test_a_foreign_agent_binary_is_not_mistaken_for_cursor():
    """`agent` is a generic name; the old code returned any PATH hit."""
    with patch("shutil.which", return_value="/usr/local/bin/agent"), \
         patch("subprocess.run", return_value=_proc("some-other-tool v1.2")):
        assert find_cursor_cli() is None


def test_cursors_own_agent_is_accepted():
    with patch("shutil.which", return_value="/usr/local/bin/agent"), \
         patch("subprocess.run", return_value=_proc("Cursor Agent 2026.9.1")):
        assert find_cursor_cli() == "/usr/local/bin/agent"


# ── sign-in tells the truth ──────────────────────────────────────────────
def test_signin_points_at_the_cli_instead_of_a_dead_browser_flow():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=None), \
         patch("webbrowser.open", side_effect=AssertionError("opened a useless page")):
        body = TestClient(app).post("/api/providers/cursor/signin").json()
    assert body["started"] is False
    assert body["cli_required"] is True
    assert "cursor.com/install" in body["detail"]


def test_signin_detects_an_installed_cli():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT):
        body = TestClient(app).post("/api/providers/cursor/signin").json()
    assert body["cli_found"] is True
    assert "agent login" in body["detail"]


@pytest.mark.parametrize("stdout,expect", [
    ('{"result":"a"}', "a"),
    ('noise\n{"result":"b"}', "b"),
    ("", None),
])
def test_shared_cli_json_parser(stdout, expect):
    assert parse_cli_json(stdout).get("result") == expect
