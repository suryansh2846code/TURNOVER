"""Unit tests for Native AI Account detection, sign-in flows, and Gemini OAuth reflection."""
from __future__ import annotations

from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.models.accounts import (
    connect_local_account,
    detect_all_accounts,
    detect_claude_account,
    detect_cursor_account,
    detect_google_account,
)
from lodestone.models.connections import ConnectionStatus, get_connection
from lodestone.models.gemini import GeminiProvider
from lodestone.models.registry import list_providers


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


def test_gemini_oauth_reflection():
    """Verify that Google OAuth sign-in reflects in Gemini provider readiness and status."""
    from lodestone.config import get_settings
    import json

    home = get_settings().home
    token_file = home / "google_token.json"
    acct_file = home / "google_account.json"
    token_file.write_text(json.dumps({"token": "mock-token", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}))
    acct_file.write_text(json.dumps({"email": "test-user@gmail.com"}))

    try:
        prov = GeminiProvider()
        ready, reason = prov.is_ready()
        assert ready is True

        # Call /api/google/status and verify Gemini connection is updated
        resp = client.get("/api/google/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["account"] == "test-user@gmail.com"

        conn = get_connection("gemini")
        assert conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED
        assert conn.email == "test-user@gmail.com"
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


def test_signin_endpoints():
    """Verify POST /api/providers/{name}/signin returns started status."""
    for p in ["openai", "xai", "claude", "cursor"]:
        resp = client.post(f"/api/providers/{p}/signin")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("started") is True


def test_openai_chatgpt_oauth_flow():
    """Verify OpenAI signin starts ChatGPT OAuth PKCE flow with official client."""
    from lodestone.models.chatgpt_auth import CLIENT_ID, AUTH_BASE_URL, detect_chatgpt_local_session, adopt_local_chatgpt_session

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
        ok, msg, conn_dict = adopt_local_chatgpt_session()
        assert ok is True
        assert conn_dict.get("email") == info["email"]
        assert conn_dict.get("connection_status") == ConnectionStatus.ACCOUNT_CONNECTED


def test_disconnect_provider():
    """Verify disconnecting a provider clears account email, tokens and sets status to DISCONNECTED."""
    from lodestone.models.connections import get_connection, ConnectionStatus
    from lodestone.models.accounts import detect_openai_account

    # 1. Connect or simulate connected account
    conn = get_connection("openai")
    conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
    conn.email = "test@example.com"
    conn.auth_method = "account"
    from lodestone.models.connections import save_connection
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



