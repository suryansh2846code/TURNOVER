"""Unit tests for Native AI Account detection, sign-in flows, and Gemini OAuth reflection."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from chitragupta.api.app import app
from chitragupta.models.accounts import (
    detect_all_accounts,
    detect_claude_account,
    detect_cursor_account,
)
from chitragupta.models.connections import ConnectionStatus, get_connection
from chitragupta.models.gemini import GeminiProvider

client = TestClient(app)


def test_detect_all_accounts():
    """Verify local account detection finds on-computer sessions safely."""
    accounts = detect_all_accounts()
    assert "gemini" in accounts
    assert "claude" in accounts
    assert "cursor" in accounts
    assert "openai" in accounts
    assert "xai" in accounts

    # Verify structure
    assert "found_on_computer" in accounts["claude"]
    assert "found_on_computer" in accounts["cursor"]
    assert "found_on_computer" in accounts["gemini"]


def test_gemini_oauth_reflection(monkeypatch):
    """Verify that Google Workspace OAuth does NOT reflect into Gemini model provider (Gemini is pure API key)."""
    import json

    from chitragupta.config import get_settings

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings().set_secret("GEMINI_API_KEY", None)

    home = get_settings().home
    token_file = home / "google_token.json"
    acct_file = home / "google_account.json"

    # 1. Non-generative scopes (e.g. Gmail only) must NOT mark Gemini model provider ready
    token_file.write_text(json.dumps({"token": "mock-token", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}))
    acct_file.write_text(json.dumps({"email": "test-user@gmail.com"}))
    try:
        prov = GeminiProvider()
        ready, _ = prov.is_ready()
        assert ready is False  # Gemini strictly requires API key

        # 2. Even if generative-language scope is in google_token.json, Gemini provider remains not ready without API key
        token_file.write_text(json.dumps({
            "token": "mock-token",
            "scopes": [
                "https://www.googleapis.com/auth/generative-language",
                "https://www.googleapis.com/auth/gmail.readonly"
            ]
        }))
        ready, _ = prov.is_ready()
        assert ready is False

        # Call /api/google/status and verify Gemini connection is NOT mutated
        resp = client.get("/api/google/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["account"] == "test-user@gmail.com"

        # 3. Providing GEMINI_API_KEY activates Gemini
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        ready, _ = prov.is_ready()
        assert ready is True
    finally:
        token_file.unlink(missing_ok=True)
        acct_file.unlink(missing_ok=True)


def test_detected_accounts_endpoint():
    """Verify GET /api/providers/detected-accounts returns local accounts."""
    resp = client.get("/api/providers/detected-accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert "accounts" in data
    assert "claude" in data["accounts"]
    assert "cursor" in data["accounts"]


def test_connect_local_claude_account():
    """Verify POST /api/providers/claude/connect-local connects detected Claude account."""
    claude_info = detect_claude_account()
    if claude_info.get("found_on_computer"):
        resp = client.post("/api/providers/claude/connect-local")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        conn = get_connection("claude")
        assert conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED
        assert conn.email == claude_info["email"]


def test_connect_local_cursor_account():
    """Verify POST /api/providers/cursor/connect-local connects detected Cursor account."""
    cursor_info = detect_cursor_account()
    if cursor_info.get("found_on_computer"):
        resp = client.post("/api/providers/cursor/connect-local")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        conn = get_connection("cursor")
        assert conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED
        assert conn.email == cursor_info["email"]


@pytest.fixture(autouse=True)
def _no_real_oauth_server(request):
    """Never bind the real OAuth loopback port from a test.

    `start_chatgpt_oauth_flow()` listens on a fixed 1455 (the redirect URI is
    registered against it, so it cannot move). Binding it for real made these
    tests fail whenever anything else held the port — including the user's own
    running app mid-sign-in.
    """
    import http.server

    if request.node.get_closest_marker("real_oauth_server"):
        yield          # this test drives the callback over HTTP for real
        return

    class _FakeServer:
        def __init__(self, *a, **kw): pass
        def serve_forever(self): pass
        def shutdown(self): pass
        def server_close(self): pass

    with patch.object(http.server, "HTTPServer", _FakeServer):
        yield


def test_signin_endpoints():
    """Providers with an interactive sign-in start one; key-only ones say so."""
    from chitragupta.models.capabilities import get_capabilities

    for p in ["openai", "xai", "claude", "cursor"]:
        resp = client.post(f"/api/providers/{p}/signin")
        assert resp.status_code == 200
        data = resp.json()
        caps = get_capabilities(p)
        if caps.api_key_only:
            # xAI has no sign-in that can yield a usable credential.
            assert data.get("started") is False
            assert data.get("api_key_only") is True
            assert data.get("key_env")
        elif data.get("cli_required"):
            # Cursor signs in through its own CLI (`agent login`), so the app
            # reports what to run instead of opening a useless browser page.
            assert data.get("started") is False
            assert data.get("detail"), "a CLI-required provider must say what to run"
        else:
            assert data.get("started") is True


def test_openai_chatgpt_oauth_flow():
    """Verify OpenAI signin starts ChatGPT OAuth PKCE flow with official client."""
    from chitragupta.models.chatgpt_auth import (
        CLIENT_ID,
        adopt_local_chatgpt_session,
        detect_chatgpt_local_session,
    )

    resp = client.post("/api/providers/openai/signin")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("started") is True
    assert "auth.openai.com" in data.get("auth_url", "")
    assert CLIENT_ID in data.get("auth_url", "")

    status_resp = client.get("/api/providers/openai/oauth-status")
    assert status_resp.status_code == 200
    assert "status" in status_resp.json()

    # Verify local session detection and adoption
    info = detect_chatgpt_local_session()
    if info and info.get("email"):
        ok, _msg, conn_dict = adopt_local_chatgpt_session()
        assert ok is True
        assert conn_dict.get("email") == info["email"]
        assert conn_dict.get("connection_status") == ConnectionStatus.ACCOUNT_CONNECTED


def test_disconnect_provider():
    """Verify disconnecting a provider clears account email, tokens and sets status to DISCONNECTED."""
    from chitragupta.models.accounts import detect_openai_account
    from chitragupta.models.connections import ConnectionStatus, get_connection

    # 1. Connect or simulate connected account
    conn = get_connection("openai")
    conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
    conn.email = "test@example.com"
    conn.auth_method = "account"
    from chitragupta.models.connections import save_connection
    save_connection(conn)

    # 2. Call disconnect endpoint
    resp = client.post("/api/providers/openai/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("disconnected") is True

    # 3. Connection record must be reset
    conn = get_connection("openai")
    assert conn.connection_status == ConnectionStatus.DISCONNECTED
    assert conn.email == ""
    assert conn.auth_method == "none"

    # 4. detect_openai_account must report connected=False
    acct = detect_openai_account()
    assert acct.get("connected") is False


def test_open_browser_endpoint(monkeypatch):
    """Verify POST /api/open-browser accepts valid URL and delegates to webbrowser.open."""
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    resp = client.post("/api/open-browser", json={"url": "https://example.com/test"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert opened == ["https://example.com/test"]

    # Empty URL rejected
    bad_resp = client.post("/api/open-browser", json={"url": ""})
    assert bad_resp.status_code == 400


@pytest.mark.real_oauth_server
def test_openai_oauth_callback_handler(monkeypatch):
    """Verify OpenAI OAuth callback handler handles /auth/callback without AttributeError and updates connection."""
    import base64
    import json
    import urllib.request

    from chitragupta.models.chatgpt_auth import _GLOBAL_AUTH_STATE, start_chatgpt_oauth_flow
    from chitragupta.models.connections import ConnectionStatus, get_connection

    # Mock httpx.post for token exchange
    dummy_payload = base64.urlsafe_b64encode(json.dumps({
        "email": "test-oauth@example.com",
        "name": "Test OAuth User",
    }).encode()).decode().rstrip("=")
    dummy_id_token = f"header.{dummy_payload}.sig"

    class DummyResp:
        status_code = 200
        def json(self):
            return {
                "access_token": "acc_12345",
                "refresh_token": "ref_12345",
                "id_token": dummy_id_token,
                "expires_in": 3600,
            }

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: DummyResp())

    # Bind an ephemeral port rather than the registered 1455: the fixed port is
    # regularly held by a running Chitragupta mid-sign-in, and a test that fails
    # for that reason teaches nothing.
    monkeypatch.setattr("chitragupta.models.chatgpt_auth.REDIRECT_PORT", 0)

    ok, _auth_url, msg = start_chatgpt_oauth_flow()
    assert ok is True, msg
    port = _GLOBAL_AUTH_STATE.server.server_address[1]

    # Call callback with valid state
    state = _GLOBAL_AUTH_STATE.state
    callback_url = f"http://127.0.0.1:{port}/auth/callback?code=ac_test_code_123&state={state}"

    req = urllib.request.Request(callback_url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "Authorization Successful" in html
        assert "test-oauth@example.com" in html

    conn = get_connection("openai")
    assert conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED
    assert conn.email == "test-oauth@example.com"


def test_openai_local_session_token_retrieval(tmp_path, monkeypatch):
    """Verify that OpenAICompatProvider and get_chatgpt_access_token resolve tokens from local sessions."""
    import json

    from chitragupta.models.chatgpt_auth import get_chatgpt_access_token
    from chitragupta.models.openai_compat import OpenAICompatProvider

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    auth_file = codex_dir / "auth.json"
    auth_file.write_text(json.dumps({
        "tokens": {
            "access_token": "valid_mock_access_token_123",
            "refresh_token": "mock_refresh_token_123",
        }
    }))

    monkeypatch.setattr("chitragupta.models.chatgpt_auth._codex_auth_path", lambda: auth_file)
    monkeypatch.setattr("chitragupta.models.chatgpt_auth._load_stored_chatgpt_data", lambda: None)

    token = get_chatgpt_access_token()
    assert token == "valid_mock_access_token_123"

    p = OpenAICompatProvider(api_key="")
    ready, _reason = p.is_ready()
    assert ready is True




