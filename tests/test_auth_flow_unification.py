"""One sign-in protocol for every provider.

Each provider had its own module, its own state machine and its own route
(`/providers/openai/oauth-status`, `/providers/xai/oauth-status`,
`/providers/claude/oauth-status`, `/providers/claude/submit-code`), so the API
and the UI special-cased providers by name. `models/auth_flows.py` is the single
seam; these tests pin the contract so adding a provider needs no new route.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from web_sources import app_source

from chitragupta.api.app import app
from chitragupta.models.auth_flows import (
    ApiKeyOnlyFlow,
    AuthStart,
    AuthStatus,
    BrowserFlow,
    ChatGPTFlow,
    ClaudeFlow,
    CursorFlow,
    GrokFlow,
    get_flow,
)

PROVIDERS = ["openai", "claude", "cursor", "xai", "gemini", "deepseek", "ollama"]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_sign_in():
    """Never start an actual sign-in from a test.

    `start_claude_login_flow()` spawns `claude auth login` and a thread watching
    the developer's real ~/.claude.json, which writes ACCOUNT_CONNECTED when it
    fires — a background write that raced other tests. These tests are about the
    protocol's shape, not about really authenticating.
    """
    with patch("webbrowser.open", return_value=True), \
         patch("chitragupta.models.claude_auth.start_claude_login_flow",
               return_value=(True, "https://claude.ai/oauth/authorize?x=1", "Opened Claude")), \
         patch("chitragupta.models.chatgpt_auth.start_chatgpt_oauth_flow",
               return_value=(True, "https://auth.openai.com/oauth/authorize?x=1", "waiting")):
        yield


# ── the protocol ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("pid,expected", [
    ("openai", ChatGPTFlow), ("anthropic", ClaudeFlow), ("claude", ClaudeFlow),
    ("cursor", CursorFlow), ("xai", GrokFlow), ("grok", GrokFlow),
    ("gemini", ApiKeyOnlyFlow), ("google", ApiKeyOnlyFlow),
    ("deepseek", ApiKeyOnlyFlow), ("ollama", BrowserFlow),
])
def test_flow_is_chosen_by_capability_not_by_name(pid, expected):
    assert isinstance(get_flow(pid), expected)


@pytest.mark.parametrize("pid", PROVIDERS)
def test_every_provider_answers_the_same_two_calls(pid, client):
    start = client.post(f"/api/providers/{pid}/auth/start")
    status = client.get(f"/api/providers/{pid}/auth/status")
    assert start.status_code == 200 and status.status_code == 200
    assert start.json()["provider_id"]
    assert status.json()["status"] in {"idle", "waiting", "success", "error"}


@pytest.mark.parametrize("pid", PROVIDERS)
def test_a_flow_never_raises(pid):
    """A provider that cannot sign in returns a reason, not an exception."""
    flow = get_flow(pid)
    assert isinstance(flow.start(), AuthStart)
    assert isinstance(flow.status(), AuthStatus)


def test_xai_signs_in_through_its_cli_not_oauth():
    """The OAuth flow in models/xai_auth.py authenticates at api.x.ai and is
    then refused for billing, so it can never yield a usable credential. The
    subscription path is xAI's own CLI."""
    from chitragupta.models.auth_flows import _FLOWS

    assert isinstance(_FLOWS["xai"], GrokFlow)
    start = get_flow("xai").start()
    assert start.cli_required is True
    assert start.started is False, "there is no browser flow to start"


# ── code submission ──────────────────────────────────────────────────────
def test_code_submission_reaches_the_flow(client):
    with patch("chitragupta.models.claude_auth.submit_claude_auth_code",
               return_value=(True, "Authenticated as a@b.com")) as sub:
        r = client.post("/api/providers/claude/auth/code", json={"code": "abc#state"})
    assert r.status_code == 200 and r.json()["ok"] is True
    sub.assert_called_once_with("abc#state")


def test_a_flow_without_code_submission_says_so(client):
    r = client.post("/api/providers/openai/auth/code", json={"code": "x"})
    assert r.status_code == 400
    assert "authorization code" in r.json()["detail"]


def test_an_empty_code_is_rejected(client):
    assert client.post("/api/providers/claude/auth/code", json={"code": "  "}).status_code == 400


def test_cancel_is_safe_for_flows_that_do_not_support_it(client):
    assert client.post("/api/providers/gemini/auth/cancel").json()["cancelled"] is True


# ── the old routes keep working ──────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/api/providers/openai/oauth-status",
    "/api/providers/xai/oauth-status",
    "/api/providers/claude/oauth-status",
])
def test_legacy_status_routes_still_answer(path, client):
    r = client.get(path)
    assert r.status_code == 200 and "status" in r.json()


def test_legacy_signin_route_still_answers(client):
    r = client.post("/api/providers/gemini/signin")
    assert r.status_code == 200 and r.json()["api_key_only"] is True


def test_legacy_submit_code_route_still_answers(client):
    with patch("chitragupta.models.claude_auth.submit_claude_auth_code",
               return_value=(True, "ok")):
        assert client.post("/api/providers/claude/submit-code",
                           json={"code": "abc"}).status_code == 200


def test_frontend_uses_the_unified_routes():

    src = app_source()
    assert "/auth/start" in src and "/auth/status" in src and "/auth/code" in src
    assert "/oauth-status" not in src, "frontend still calls a per-provider route"
