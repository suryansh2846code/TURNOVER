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
from web_sources import app_source

from lodestone.api.app import app
from lodestone.models.base import Message, parse_cli_json
from lodestone.models.cursor import CursorProvider, find_cursor_cli

HELLO = [Message(role="user", content="hi")]


class _Running:
    def poll(self): return None


class _Exited:
    def poll(self): return 0
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
    assert body["cli_installable"] is True, "we can fetch the CLI — offer to"
    assert "install it for you" in body["detail"]


def test_signin_runs_the_cli_browser_login_when_installed():
    """`agent login` opens authenticator.cursor.sh itself — the OAuth client
    belongs to the CLI — so we spawn it and poll, giving the same
    click -> browser -> connected flow as any other provider."""
    spawned = {}

    def fake_popen(cmd, **kw):
        spawned["cmd"] = cmd
        return object()

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc('{"isAuthenticated": false}')), \
         patch("subprocess.Popen", side_effect=fake_popen):
        body = TestClient(app).post("/api/providers/cursor/auth/start").json()

    assert spawned["cmd"] == [AGENT, "login"]
    assert body["started"] is True
    assert body["browser_opened"] is True
    assert body.get("cli_required") is not True


def test_status_polls_the_cli_and_connects_on_success():
    from lodestone.models import cursor as mod
    from lodestone.models.connections import ProviderConnection, get_connection, save_connection

    save_connection(ProviderConnection(provider="cursor"))

    # Nothing in flight and not signed in -> idle. "waiting" means a sign-in we
    # started is still running.
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc('{"isAuthenticated": false}')):
        assert TestClient(app).get("/api/providers/cursor/auth/status").json()["status"] == "idle"

    mod._session.proc, mod._session.baseline = _Running(), {"authenticated": False, "email": None}
    mod.reset_auth_cache()
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc('{"isAuthenticated": false}')):
        assert TestClient(app).get("/api/providers/cursor/auth/status").json()["status"] == "waiting"
    mod.reset_login_state()

    # Sign-in state is cached for a few seconds so polling doesn't spawn a
    # subprocess per tick; a completed login is noticed once that lapses.
    from lodestone.models.cursor import reset_auth_cache
    reset_auth_cache()

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run",
               return_value=_proc('{"isAuthenticated": true, "email": "me@example.com"}')):
        body = TestClient(app).get("/api/providers/cursor/auth/status").json()
    assert body["status"] == "success"
    assert get_connection("cursor").account_connected is True
    save_connection(ProviderConnection(provider="cursor"))


@pytest.mark.parametrize("stdout,expect", [
    ('{"result":"a"}', "a"),
    ('noise\n{"result":"b"}', "b"),
    ("", None),
])
def test_shared_cli_json_parser(stdout, expect):
    assert parse_cli_json(stdout).get("result") == expect


# ── the button must explain itself ───────────────────────────────────────
def test_signin_handler_branches_on_the_backend_answer():
    """The handler used to show "Waiting for Cursor sign-in… finish in your
    browser" and toast "Opening Cursor in browser…" regardless of the response.
    For a CLI-only provider that is a spinner waiting for something that never
    happens."""

    src = app_source()
    handler = src[src.index("const signinBtn = boxEl.querySelector"):]
    handler = handler[:handler.index("// Connect via API key")] if "// Connect via API key" in handler else handler

    assert "res.started === false" in handler, "handler ignores a flow that did not start"
    assert "res.cli_required" in handler, "handler has no CLI-required branch"
    assert "showCliInstructions" in handler
    # the browser toast must be gated behind an actually-started flow
    opening = handler.index("Opening ${brandName} in browser")
    branch = handler.index("res.started === false")
    assert branch < opening, "still claims to open a browser before checking"


def test_cli_instructions_surface_the_command():

    src = app_source()
    fn = src[src.index("function showCliInstructions"):]
    fn = fn[:fn.index("\nfunction ")]
    assert "ts-cli-install" in fn, "no one-click install path"
    assert "ts-cli-cmd" in fn and "clipboard" in fn, "no copyable-command fallback"
    assert "ts-cli-recheck" in fn, "no way to re-check after signing in"


# ── the signed-in CLI is the identity, and refresh completes a sign-in ───
CLI_AUTHED = """{
  "status": "authenticated",
  "isAuthenticated": true,
  "userInfo": {"email": "new@example.com", "firstName": "New", "lastName": "User"}
}"""


def test_identity_is_read_from_the_nested_userInfo():
    """`agent status --format json` nests it; reading the top level found
    nothing, so the card kept showing a stale account."""
    from lodestone.models.cursor import cursor_cli_auth_status

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc(CLI_AUTHED)):
        st = cursor_cli_auth_status()
    assert st["authenticated"] is True
    assert st["email"] == "new@example.com"
    assert st["name"] == "New User"


def test_the_cli_account_beats_the_cursor_apps_cached_one():
    """The Cursor *app* caches a different account in its sqlite. The CLI is
    what we actually run, so after signing in there its identity must win."""
    from lodestone.models.accounts import detect_cursor_account

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc(CLI_AUTHED)):
        acct = detect_cursor_account()
    assert acct["email"] == "new@example.com"
    assert acct["auth_method"] == "cli"


def test_refresh_finishes_a_sign_in_the_poll_gave_up_on():
    """A browser login completes long after the HUD stops polling, so Refresh
    must adopt it rather than being decorative."""
    from lodestone.models.connections import ProviderConnection, get_connection, save_connection

    save_connection(ProviderConnection(provider="cursor"))
    with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
         patch("subprocess.run", return_value=_proc(CLI_AUTHED)):
        assert TestClient(app).post("/api/providers/cursor/refresh").status_code == 200

    conn = get_connection("cursor")
    assert conn.account_connected is True
    assert conn.email == "new@example.com"
    save_connection(ProviderConnection(provider="cursor"))


def test_the_waiting_hud_polls_every_provider():
    """It gated /auth/status on a hardcoded ["openai","xai","claude"] list, so
    Cursor's sign-in was never polled at all."""

    src = app_source()
    hud = src[src.index("function showWaitingHud"):]
    hud = hud[:hud.index("\nfunction ")]
    assert '["openai", "xai", "claude"].includes' not in hud
    assert "/auth/status" in hud
    assert "MAX_ATTEMPTS" in hud, "no explicit wait budget"
    assert "press Refresh" in hud, "a timeout must say what to do next"


# ── a re-sign-in must not be satisfied by the existing session ───────────
def _flow_status(proc, baseline, cli_json):
    from lodestone.models import cursor as mod
    from lodestone.models.auth_flows import get_flow

    mod._session.proc, mod._session.baseline = proc, baseline
    mod.reset_auth_cache()
    try:
        with patch("lodestone.models.cursor.find_cursor_cli", return_value=AGENT), \
             patch("subprocess.run", return_value=_proc(cli_json)):
            return get_flow("cursor").status().status
    finally:
        mod._session.proc, mod._session.baseline = None, None
        mod.reset_auth_cache()


SAME = '{"isAuthenticated": true, "userInfo": {"email": "me@example.com"}}'
OTHER = '{"isAuthenticated": true, "userInfo": {"email": "new@example.com"}}'
BASE = {"authenticated": True, "email": "me@example.com"}


def test_signing_in_again_waits_instead_of_reporting_the_old_session():
    """Clicking Sign in while already signed in used to report success on the
    first poll — before the user had touched the browser — tearing down the
    waiting row and the floating card immediately."""
    assert _flow_status(_Running(), BASE, SAME) == "waiting"


def test_switching_to_a_different_account_is_noticed():
    assert _flow_status(_Running(), BASE, OTHER) == "success"


def test_finishing_in_the_browser_completes_it():
    """The CLI's login process exiting is the real completion signal."""
    assert _flow_status(_Exited(), BASE, SAME) == "success"


def test_no_sign_in_running_just_reports_the_current_state():
    assert _flow_status(None, None, SAME) == "success"
    assert _flow_status(None, None, '{"isAuthenticated": false}') == "idle"


def test_cancelling_clears_the_in_flight_state():
    from lodestone.models import cursor as mod

    mod._session.proc, mod._session.baseline = _Running(), BASE
    with patch.object(_Running, "terminate", create=True):
        mod.cancel_cli_login()
    assert mod.login_progress()["in_flight"] is False
