"""Hardening tests for Gemini authentication, credential resolution, error classification, and secret redaction."""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from lodestone.models.connections import ConnectionStatus, get_connection, save_connection
from lodestone.models.gemini import (
    GeminiCredentialSource,
    GeminiErrorCode,
    GeminiProvider,
    classify_gemini_error,
    has_gemini_scope,
    resolve_gemini_credentials,
)
from lodestone.models.accounts import detect_google_account, connect_local_account
from lodestone.models.entitlements import is_provider_connected


@pytest.fixture(autouse=True)
def clean_gemini_env(monkeypatch, tmp_path):
    """Ensure environment is isolated for Gemini tests."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("lodestone.config.Settings.get_secret", lambda self, key: os.environ.get(key))

    conn = get_connection("gemini")
    conn.connection_status = ConnectionStatus.NOT_CONNECTED
    conn.auth_method = "api_key"
    conn.email = None
    save_connection(conn)

    # Point google auth token path to empty tmp path
    fake_token = tmp_path / "google_token.json"
    with patch("lodestone.connectors.google_auth._token_path", return_value=fake_token):
        yield fake_token


def test_has_gemini_scope():
    """Verify scope classification."""
    assert has_gemini_scope(None) is False
    assert has_gemini_scope([]) is False
    assert has_gemini_scope(["https://www.googleapis.com/auth/gmail.readonly"]) is False
    assert has_gemini_scope(["https://www.googleapis.com/auth/drive.readonly"]) is False
    assert has_gemini_scope(["https://www.googleapis.com/auth/calendar.events"]) is False
    assert has_gemini_scope(["https://www.googleapis.com/auth/generative-language"]) is True
    assert has_gemini_scope(["https://www.googleapis.com/auth/generative-language.retriever"]) is True
    assert has_gemini_scope(["https://www.googleapis.com/auth/cloud-platform"]) is True


def test_resolve_credentials_none():
    """When no key or token is configured, return NONE source."""
    cred = resolve_gemini_credentials()
    assert cred.source == GeminiCredentialSource.NONE
    assert cred.valid is False
    assert "not connected" in cred.error_reason.lower()


def test_resolve_credentials_api_key(monkeypatch):
    """Explicit API key takes standard precedence and populates API_KEY source."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-123")
    cred = resolve_gemini_credentials()
    assert cred.source == GeminiCredentialSource.API_KEY
    assert cred.valid is True
    assert cred.secret == "test-gemini-key-123"


def test_resolve_credentials_workspace_token_ignored(clean_gemini_env):
    """Google Workspace OAuth tokens must be ignored by Gemini (Gemini is pure API key)."""
    token_file = clean_gemini_env
    token_file.write_text(json.dumps({
        "token": "workspace-token-abc",
        "scopes": [
            "https://www.googleapis.com/auth/generative-language",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "email": "workspace-user@example.com"
    }))

    cred = resolve_gemini_credentials()
    assert cred.valid is False
    assert cred.source == GeminiCredentialSource.NONE
    assert "GEMINI_API_KEY" in cred.error_reason or "not connected" in cred.error_reason.lower()


def test_resolve_credentials_google_api_key_fallback(monkeypatch):
    """GOOGLE_API_KEY fallback works if GEMINI_API_KEY is not set."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fallback-google-key")
    cred = resolve_gemini_credentials()
    assert cred.source == GeminiCredentialSource.API_KEY
    assert cred.valid is True
    assert cred.secret == "fallback-google-key"


def test_force_source_enforcement(monkeypatch):
    """force_source must enforce API_KEY source."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-456")
    cred_key = resolve_gemini_credentials(force_source=GeminiCredentialSource.API_KEY)
    assert cred_key.source == GeminiCredentialSource.API_KEY
    assert cred_key.valid is True
    assert cred_key.secret == "key-456"

    # When no key is set and API_KEY is forced, valid is False
    monkeypatch.delenv("GEMINI_API_KEY")
    cred_none = resolve_gemini_credentials(force_source=GeminiCredentialSource.API_KEY)
    assert cred_none.valid is False
    assert cred_none.source == GeminiCredentialSource.NONE


def test_error_classification_and_redaction():
    """Verify classification of HTTP statuses and redaction of secret tokens/keys."""
    raw_401 = '{"error": {"message": "API key not valid. Please pass a valid API key: key=AIzaSyD-secret-key-1234"}}'
    code, msg = classify_gemini_error(401, raw_401, model="gemini-2.5-flash")
    assert code == GeminiErrorCode.AUTHENTICATION_FAILED
    assert "AIzaSyD-secret-key-1234" not in msg
    assert "REDACTED" in msg
    assert "credential is invalid or expired" in msg

    raw_403 = '{"error": {"message": "Method doesn\'t allow unregistered callers (caller: Bearer ya29.a0AfH6SM-secret-token)"}}'
    code, msg = classify_gemini_error(403, raw_403, model="gemini-2.5-flash")
    assert code == GeminiErrorCode.PERMISSION_DENIED
    assert "ya29.a0AfH6SM-secret-token" not in msg
    assert "Permission denied" in msg

    code, msg = classify_gemini_error(404, '{"error": {"message": "models/non-existent-model is not found"}}', model="gemini-custom")
    assert code == GeminiErrorCode.MODEL_NOT_FOUND
    assert "gemini-custom" in msg

    code, msg = classify_gemini_error(429, '{"error": {"message": "Resource has been exhausted (e.g. check quota)."}}')
    assert code == GeminiErrorCode.RATE_LIMITED
    assert "quota or rate limit" in msg.lower()

    code, msg = classify_gemini_error(500, '{"error": {"message": "Internal error occurred."}}')
    assert code == GeminiErrorCode.SERVER_ERROR
    assert "Google Gemini temporary server error" in msg

    code, msg = classify_gemini_error(0, "Connection timed out", model="gemini-2.5-flash")
    assert code == GeminiErrorCode.NETWORK_ERROR
    assert "timed out" in msg.lower() or "network" in msg.lower()


def test_gemini_provider_is_ready_and_chat_safety():
    """GeminiProvider.is_ready() must accurately reflect credential state without making erroneous chat calls."""
    from lodestone.models.base import Message
    prov = GeminiProvider(model="gemini-2.5-flash")
    ready, reason = prov.is_ready()
    assert ready is False
    assert "not connected" in reason.lower() or "gemini_api_key" in reason.lower()

    # Calling chat when not ready must return clean error without throwing or leaking
    res = prov.chat([Message(role="user", content="Hello")])
    assert "⚠️" in res.text
    assert "GEMINI_API_KEY" in res.text or "not connected" in res.text.lower()


def test_entitlements_and_account_detection(clean_gemini_env, monkeypatch):
    """Verify is_provider_connected and detect_google_account behavior with Workspace vs API key."""
    # 1. No credentials
    connected, plan, meta = is_provider_connected("gemini")
    assert connected is False

    acct = detect_google_account()
    assert acct["connected"] is False
    assert acct["found_on_computer"] is False

    # 2. Workspace token only - must not affect Gemini account detection
    token_file = clean_gemini_env
    token_file.write_text(json.dumps({
        "token": "ws-token",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "email": "user@workspace.com"
    }))

    connected, plan, meta = is_provider_connected("gemini")
    assert connected is False

    acct = detect_google_account()
    assert acct["found_on_computer"] is False
    assert acct["connected"] is False

    # Trying to connect local account without API key should inform user that API key is needed
    ok, msg, _ = connect_local_account("gemini")
    assert ok is False
    assert "GEMINI_API_KEY" in msg

    # 3. With API key provided, entitlements and account detection report connected
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-789")
    connected, plan, meta = is_provider_connected("gemini")
    assert connected is True
    assert meta["source"] == "api_key"

    acct = detect_google_account()
    assert acct["connected"] is True
    assert acct["has_api_key"] is True
    assert acct["auth_method"] == "api_key"

    # connect_local_account with API key binds to API_KEY_CONNECTED
    ok, msg, conn_dict = connect_local_account("gemini")
    assert ok is True
    assert conn_dict["connection_status"] == ConnectionStatus.API_KEY_CONNECTED
