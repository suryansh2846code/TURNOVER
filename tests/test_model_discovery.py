"""Unit tests for Dynamic Model Discovery."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.models.discovery import (
    _detect_capabilities,
    discover_anthropic_models,
    discover_openai_models,
    discover_xai_models,
    get_discovered_models,
)


def test_capability_detection():
    """Verify reasoning, vision, and tool calling capability detection."""
    o1_caps = _detect_capabilities("o1-preview")
    assert o1_caps["reasoning"] is True
    assert o1_caps["tool_calling"] is True

    sonnet_caps = _detect_capabilities("claude-3-7-sonnet-latest")
    assert sonnet_caps["reasoning"] is True
    assert sonnet_caps["vision"] is True
    assert sonnet_caps["context_window"] == 200_000

    gemini_caps = _detect_capabilities("gemini-2.5-flash")
    assert gemini_caps["context_window"] == 1_000_000
    assert gemini_caps["vision"] is True


def test_mocked_openai_discovery():
    """Verify live OpenAI discovery parser and identity lookup."""
    mock_resp_me = MagicMock()
    mock_resp_me.status_code = 200
    mock_resp_me.json.return_value = {
        "id": "user_xyz",
        "email": "developer@turnover.ai",
        "name": "TURNOVER Developer",
        "orgs": {"data": [{"name": "Acme AI Corp", "id": "org_123"}]},
    }

    mock_resp_models = MagicMock()
    mock_resp_models.status_code = 200
    mock_resp_models.json.return_value = {
        "data": [
            {"id": "gpt-4o", "created": 1700000000},
            {"id": "gpt-4o-mini", "created": 1700000100},
            {"id": "o1", "created": 1700000200},
            {"id": "text-embedding-3-small", "created": 1690000000},  # should be filtered out
        ]
    }

    def mock_get(url, **kwargs):
        if "v1/me" in url:
            return mock_resp_me
        return mock_resp_models

    with patch("httpx.get", side_effect=mock_get):
        models, account_meta = discover_openai_models(api_key="sk-test-key")
        assert account_meta.get("email") == "developer@turnover.ai"
        assert account_meta.get("organization") == "Acme AI Corp"
        m_ids = [m.id for m in models]
        assert "gpt-4o" in m_ids
        assert "o1" in m_ids
        assert "text-embedding-3-small" not in m_ids


def test_mocked_xai_discovery_prevents_stale_models():
    """Verify xAI returns real discovered model list, eliminating grok-2-latest not found."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"id": "grok-2-1212"},
            {"id": "grok-2-vision-1212"},
            {"id": "grok-beta"},
        ]
    }
    with patch("httpx.get", return_value=mock_resp):
        models = discover_xai_models(api_key="xai-test-key")
        m_ids = [m.id for m in models]
        assert "grok-2-1212" in m_ids
        assert "grok-2-vision-1212" in m_ids


def test_models_api_endpoint():
    """Verify GET /api/providers/{name}/models endpoint."""
    client = TestClient(app)
    resp = client.get("/api/providers/ollama/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert len(data["models"]) > 0
