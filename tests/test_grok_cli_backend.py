"""xAI's subscription runs through its official CLI.

`api.x.ai` is the developer API, billed from console.x.ai credits, and a
SuperGrok subscription grants none — verified against a real account, where even
`GET /v1/models` returns 403 personal-team-blocked:spending-limit. The
sanctioned subscription path is xAI's own agentic CLI, Grok Build:

    grok -p "<prompt>" --output-format json -m <model>

Same shape as the Claude Code and Cursor backends.
"""
import subprocess
from unittest.mock import patch

import pytest

from lodestone.models.base import Message
from lodestone.models.grok_cli import GrokCliProvider, find_grok_cli, grok_cli_models
from lodestone.models.xai import XAIProvider

HELLO = [Message(role="user", content="hi")]
GROK = "/Users/me/.local/bin/grok"

# Real `grok models` output, captured from the CLI 2026-09-12.
MODELS_OUT = """You are not authenticated.

Default model: grok-4.6

Available models:
  * grok-4.6 (default)
  - grok-4.5
"""


def _cp(code=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


# ── routing: subscription -> CLI, key -> api.x.ai ────────────────────────
def test_a_subscription_never_calls_the_developer_api():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("lodestone.models.base._saved_key", return_value=""), \
         patch("subprocess.run", return_value=_cp(0, '{"result":"from the CLI"}')), \
         patch("httpx.post", side_effect=AssertionError("posted to api.x.ai")):
        assert XAIProvider(api_key=None).chat(HELLO).text == "from the CLI"


def test_an_api_key_still_uses_the_developer_api():
    import httpx

    resp = httpx.Response(200, request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
                          json={"choices": [{"message": {"content": "from the API"}}]})
    with patch("httpx.post", return_value=resp), \
         patch("subprocess.run", side_effect=AssertionError("shelled out despite a key")):
        assert "from the API" in XAIProvider(api_key="xai-real-key").chat(HELLO).text


def test_ready_when_the_cli_is_present_and_signed_in():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("lodestone.models.grok_cli.grok_cli_auth_status",
               return_value={"installed": True, "authenticated": True}), \
         patch("lodestone.models.base._saved_key", return_value=""):
        assert XAIProvider(api_key=None).is_ready() == (True, "")


def test_an_installed_but_signed_out_cli_is_not_ready():
    """Reported from the running app, with a screenshot of the chat.

    Readiness asked only whether the binary existed. So a CLI that had never
    been signed in reported ready, `/refresh` wrote API_KEY_CONNECTED for an
    account holding no credential at all, the drawer put a green "Connected"
    badge on xAI — and the first message reached `grok -p`, which answered

        Not signed in. To authenticate without a browser, run:
          grok login --device-code

    which was then rendered as the agent's reply. Every one of those surfaces
    was downstream of this function returning True.
    """
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("lodestone.models.grok_cli.grok_cli_auth_status",
               return_value={"installed": True, "authenticated": False}), \
         patch("lodestone.models.base._saved_key", return_value=""):
        ready, reason = XAIProvider(api_key=None).is_ready()
    assert ready is False
    assert "Models" in reason, "the way out must be named, in the app"
    assert "--device-code" not in reason and "$" not in reason


def test_without_key_or_cli_it_explains_both_options():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=None), \
         patch("lodestone.models.base._saved_key", return_value=""):
        ready, reason = XAIProvider(api_key=None).is_ready()
    assert ready is False
    assert "XAI_API_KEY" in reason and "Models" in reason


# ── the CLI contract ─────────────────────────────────────────────────────
def test_headless_invocation_matches_the_documented_flags():
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _cp(0, '{"result":"ok"}')

    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", side_effect=fake_run):
        GrokCliProvider(model="grok-4.5").chat(HELLO)

    cmd = seen["cmd"]
    assert cmd[0] == GROK
    assert "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("-m") + 1] == "grok-4.5"


def test_system_context_is_folded_into_the_single_prompt():
    seen = {}
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run",
               side_effect=lambda cmd, **kw: (seen.setdefault("cmd", cmd), _cp(0, '{"result":"ok"}'))[1]):
        GrokCliProvider().chat([
            Message(role="system", content="You are terse."),
            Message(role="user", content="earlier"),
            Message(role="assistant", content="noted"),
            Message(role="user", content="now this"),
        ])
    prompt = seen["cmd"][seen["cmd"].index("-p") + 1]
    assert "You are terse." in prompt and "now this" in prompt
    assert "Recent conversation so far" in prompt


@pytest.mark.parametrize("payload,expect", [
    ('{"result":"a"}', "a"),
    ('{"text":"b"}', "b"),
    ('{"response":"c"}', "c"),
    ('noise line\n{"result":"d"}', "d"),
])
def test_response_shapes_are_tolerated(payload, expect):
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, payload)):
        assert GrokCliProvider().chat(HELLO).text == expect


def test_not_signed_in_is_explained_in_the_app():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(1, "", "You are not authenticated")):
        text = GrokCliProvider().chat(HELLO).text
    assert "Sign in with Grok" in text
    assert "grok login" not in text, "the user was sent to a terminal"


# The exact payload the CLI prints when it is not signed in, captured from
# `grok -p "say OK" --output-format json` on 2026-09-13.
NOT_SIGNED_IN = (
    '{"type":"error","message":"Not signed in. To authenticate without a '
    'browser, run:\\n  grok login --device-code\\n\\nAlternatively, set the '
    'XAI_API_KEY environment variable or run `grok login` on a machine with a '
    'browser."}'
)


def test_the_cli_error_text_is_never_returned_as_the_answer():
    """A failed call fell through to `if text: return ChatResult(text=text)`,
    and `text` was whatever the CLI had written — so the vendor's own error,
    including two terminal commands, was rendered as the agent's reply in the
    chat transcript. A failure gets our message, or none."""
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(1, NOT_SIGNED_IN)):
        text = GrokCliProvider().chat(HELLO).text
    assert "--device-code" not in text
    assert "Not signed in. To authenticate" not in text
    assert "Sign in with Grok" in text


def test_timeout_is_reported_not_raised():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired("grok", 180)):
        assert "timed out" in GrokCliProvider().chat(HELLO).text


def test_missing_cli_points_at_the_install_we_run_ourselves():
    """We download and pin this CLI (`models/cli_manager.py`), so the answer is
    a button in Models & Accounts — not a curl command the user must paste."""
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=None):
        text = GrokCliProvider().chat(HELLO).text
    assert "Models" in text and "Install" in text
    assert "curl" not in text


# ── discovery comes from the account, not a hardcoded list ───────────────
def test_models_are_parsed_from_the_cli_listing():
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, MODELS_OUT)):
        assert grok_cli_models() == ["grok-4.6", "grok-4.5"]


def test_discovery_uses_the_cli_when_there_is_no_key():
    from lodestone.models.discovery import discover_xai_models

    with patch("lodestone.models.base._saved_key", return_value=""), \
         patch("lodestone.models.grok_cli.grok_cli_models", return_value=["grok-4.6", "grok-4.5"]):
        models = discover_xai_models(api_key=None)
    ids = [m.id for m in models]
    assert ids == ["grok-4.6", "grok-4.5"]
    assert not any(m.is_fallback for m in models), "a live listing is not a fallback"


def test_binary_discovery_rejects_a_namesake():
    with patch("shutil.which", return_value="/usr/local/bin/grok"), \
         patch("subprocess.run", return_value=_cp(0, "some-other-tool v1")):
        assert find_grok_cli() is None

    with patch("shutil.which", return_value="/usr/local/bin/grok"), \
         patch("subprocess.run", return_value=_cp(0, "grok 1.0.13 (abc)")):
        assert find_grok_cli() == "/usr/local/bin/grok"


# ── sign-in points at the CLI ────────────────────────────────────────────
def test_signin_runs_the_cli_browser_login_when_installed():
    """`grok login --oauth` opens the Grok Build consent screen at
    accounts.x.ai; the OAuth client belongs to the CLI."""
    from fastapi.testclient import TestClient

    from lodestone.api.app import app

    spawned = {}
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, MODELS_OUT)), \
         patch("subprocess.Popen", side_effect=lambda cmd, **kw: spawned.setdefault("cmd", cmd)):
        body = TestClient(app).post("/api/providers/xai/auth/start").json()

    assert spawned["cmd"] == [GROK, "login", "--oauth"]
    assert body["started"] is True and body["browser_opened"] is True


def test_signin_explains_installation_when_the_cli_is_missing():
    from fastapi.testclient import TestClient

    from lodestone.api.app import app

    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=None), \
         patch("webbrowser.open", side_effect=AssertionError("opened a useless page")):
        body = TestClient(app).post("/api/providers/xai/auth/start").json()
    assert body["started"] is False and body["cli_required"] is True
    assert body["cli_installable"] is True, "we can fetch the CLI — offer to"
    assert "install it for you" in body["detail"]


def test_status_reports_waiting_then_success():
    from fastapi.testclient import TestClient

    from lodestone.api.app import app
    from lodestone.models import grok_cli as mod
    from lodestone.models.connections import ProviderConnection, get_connection, save_connection

    save_connection(ProviderConnection(provider="xai"))
    client = TestClient(app)

    # Nothing in flight -> idle; "waiting" means a sign-in we started is running.
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, MODELS_OUT)):   # "not authenticated"
        assert client.get("/api/providers/xai/auth/status").json()["status"] == "idle"

    class _Running:
        def poll(self): return None

    mod._login_proc, mod._login_baseline = _Running(), {"authenticated": False}
    mod.reset_auth_cache()
    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, MODELS_OUT)):
        assert client.get("/api/providers/xai/auth/status").json()["status"] == "waiting"
    mod.reset_login_state()

    # Cached for a few seconds so polling is cheap; a completed login is
    # noticed once that lapses.
    from lodestone.models.grok_cli import reset_auth_cache
    reset_auth_cache()

    with patch("lodestone.models.grok_cli.find_grok_cli", return_value=GROK), \
         patch("subprocess.run", return_value=_cp(0, "Available models:\n  * grok-4.6")):
        assert client.get("/api/providers/xai/auth/status").json()["status"] == "success"
    assert get_connection("xai").account_connected is True
    save_connection(ProviderConnection(provider="xai"))


# ── cancelling a sign-in ─────────────────────────────────────────────────────
# `cancel_cli_login` is byte-identical to the Cursor copy and, unlike it, had no
# test at all — `pytest --cov` put the whole body in the missing-lines column.
# These pin what it does *before* the two copies are folded into one, so the
# extraction has something to be measured against rather than a green suite that
# never executed the code.
#
# The `finally: login_processes.release(...)` is the part that matters most: an
# abandoned `login` waits for a browser callback that may never arrive, and 158
# of them once accumulated on one machine.

class _Spawned:
    """A login process that is still waiting on the browser."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid, self.terminated = pid, False

    def poll(self):
        return None                      # still running

    def terminate(self) -> None:
        self.terminated = True


class _AlreadyExited(_Spawned):
    def poll(self):
        return 0


def _tracked_pids() -> list[int]:
    from lodestone.models import login_processes

    return [r["pid"] for r in login_processes._load()]


def test_cancelling_terminates_the_login_and_stops_tracking_it():
    from lodestone.models import grok_cli as mod
    from lodestone.models import login_processes

    proc = _Spawned()
    login_processes.track(proc, "login")
    assert proc.pid in _tracked_pids()

    mod._login_proc, mod._login_baseline = proc, {"authenticated": False}
    assert mod.cancel_cli_login() is True
    assert proc.terminated is True
    # Released from the on-disk record, or the next launch reaps a PID that is
    # already gone — and, once reused, something else entirely.
    assert proc.pid not in _tracked_pids()


def test_cancelling_clears_the_in_flight_state():
    from lodestone.models import grok_cli as mod

    mod._login_proc, mod._login_baseline = _Spawned(), {"authenticated": False}
    mod.cancel_cli_login()
    assert mod._login_proc is None
    assert mod._login_baseline is None


def test_cancelling_with_nothing_in_flight_is_a_no_op():
    from lodestone.models import grok_cli as mod

    mod._login_proc = None
    assert mod.cancel_cli_login() is False


def test_cancelling_a_login_that_already_finished_reports_nothing_to_cancel():
    """The user completed it in the browser a moment before clicking cancel."""
    from lodestone.models import grok_cli as mod

    mod._login_proc = _AlreadyExited()
    assert mod.cancel_cli_login() is False


def test_a_terminate_that_fails_still_stops_tracking_the_process():
    """Bookkeeping must not be skipped because the signal did not land."""
    from lodestone.models import grok_cli as mod
    from lodestone.models import login_processes

    proc = _Spawned(pid=4243)
    login_processes.track(proc, "login")
    with patch.object(_Spawned, "terminate", side_effect=OSError("gone")):
        mod._login_proc = proc
        assert mod.cancel_cli_login() is False
    assert proc.pid not in _tracked_pids()
