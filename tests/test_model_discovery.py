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


def test_chatgpt_subscription_locks_unsupported_models():
    """Verify models not supported on user plan are flagged as locked with plan_required."""
    from lodestone.models.discovery import _chatgpt_subscription_models

    models = _chatgpt_subscription_models()
    model_map = {m.id: m for m in models}

    # Terra and Luna are available on free plan
    assert "gpt-5.6-terra" in model_map
    assert model_map["gpt-5.6-terra"].locked is False

    # Astra and Sol require Pro
    if "gpt-6-astra" in model_map:
        assert model_map["gpt-6-astra"].locked is True
        assert model_map["gpt-6-astra"].plan_required == "Pro"

    if "gpt-5.6-sol" in model_map:
        assert model_map["gpt-5.6-sol"].locked is True
        assert model_map["gpt-5.6-sol"].plan_required == "Pro"


def test_chatgpt_subscription_rejects_unsupported_model():
    """Verify chat_with_chatgpt_subscription informs user of unsupported model instead of silent fallback."""
    from lodestone.models.base import Message
    from lodestone.models.chatgpt_auth import chat_with_chatgpt_subscription

    with patch("lodestone.models.chatgpt_auth.get_chatgpt_access_token", return_value="mock_token"):
        res = chat_with_chatgpt_subscription(
            [Message(role="user", content="hello")],
            model="gpt-6-astra",
        )
        # Must return warning explaining the plan requirement, not silent success
        assert "not supported on your" in res.text
        assert "Pro" in res.text


def test_set_agent_model_api_rejects_locked_model():
    """Verify API prevents binding an agent to a locked model."""
    client = TestClient(app)
    resp = client.post("/api/agents/inbox/model", json={"provider": "openai", "model": "gpt-6-astra"})
    assert resp.status_code == 400
    assert "locked" in resp.json()["detail"].lower() or "requires" in resp.json()["detail"].lower()


def test_claude_opus_and_fable_discovery():
    """Verify Claude Opus 5, Sonnet 5, and Fable 5.1 are discovered and locked appropriately."""
    models, _ = get_discovered_models("claude")
    model_map = {m["id"]: m for m in models}

    assert "claude-opus-5" in model_map
    assert "claude-sonnet-5" in model_map
    assert "claude-fable-5-1" in model_map

    # Opus 5 capabilities
    opus = model_map["claude-opus-5"]
    assert opus.get("reasoning") is True
    assert opus.get("context_window") == 200_000

    # Fable 5.1 is locked because it requires Team or Enterprise tier
    fable = model_map["claude-fable-5-1"]
    assert fable.get("locked") is True
    assert fable.get("plan_required") in ("Team", "Enterprise", "Team / Enterprise (v2.1.255+)") or "2.1.255" in fable.get("plan_required", "")


def test_claude_code_fable_handled_gracefully():
    """Verify ClaudeCodeProvider informs user about locked model cleanly."""
    from lodestone.models.base import Message
    from lodestone.models.claude_code import ClaudeCodeProvider

    provider = ClaudeCodeProvider(model="claude-fable-5-1")
    res = provider.chat([Message(role="user", content="hello")])
    assert "currently locked" in res.text or "Fable 5.1 is currently disabled" in res.text


def test_cursor_locking_matches_plan():
    """Verify Cursor Free tier keeps cursor-fast unlocked while locking Pro models."""
    models, _ = get_discovered_models("cursor")
    model_map = {m["id"]: m for m in models}

    assert "cursor-fast" in model_map
    assert model_map["cursor-fast"].get("locked") is False

    assert "claude-opus-5" in model_map
    assert model_map["claude-opus-5"].get("locked") is True
    assert model_map["claude-opus-5"].get("plan_required") == "Pro"

