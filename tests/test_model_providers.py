"""Tests for new & enhanced model connection layer (Gemini, xAI, Cursor, DeepSeek, Claude, etc.)."""
import json
from unittest.mock import MagicMock, patch

from lodestone.models.base import Message, Tool
from lodestone.models.gemini import GeminiProvider
from lodestone.models.xai import XAIProvider
from lodestone.models.cursor import CursorProvider
from lodestone.models.deepseek import DeepSeekProvider
from lodestone.models.anthropic import AnthropicProvider
from lodestone.models.registry import (
    get_provider,
    get_model_catalog,
    context_window,
)


def test_provider_registration_and_aliases():
    """Verify all models and aliases resolve properly."""
    assert isinstance(get_provider("claude"), AnthropicProvider)
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
    assert isinstance(get_provider("gemini"), GeminiProvider)
    assert isinstance(get_provider("google"), GeminiProvider)
    assert isinstance(get_provider("xai"), XAIProvider)
    assert isinstance(get_provider("grok"), XAIProvider)
    assert isinstance(get_provider("cursor"), CursorProvider)
    assert isinstance(get_provider("deepseek"), DeepSeekProvider)


def test_model_catalog_structure():
    """Verify get_model_catalog returns all primary providers with recommended models."""
    catalog = get_model_catalog()
    assert len(catalog) >= 8
    cat_ids = [c["id"] for c in catalog]
    for expected in ["claude", "cursor", "gemini", "xai", "openai", "deepseek", "ollama"]:
        assert expected in cat_ids

    # Check Gemini catalog entry
    gemini_entry = next(c for c in catalog if c["id"] == "gemini")
    assert gemini_entry["label"] == "Google Gemini"
    assert "gemini-2.5-flash" in [m["id"] for m in gemini_entry["models"]]
    assert gemini_entry["key_env"] == "GEMINI_API_KEY"

    # Check xAI catalog entry
    xai_entry = next(c for c in catalog if c["id"] == "xai")
    assert xai_entry["label"] == "xAI (Grok)"
    assert "grok-4.6" in [m["id"] for m in xai_entry["models"]]

    # Check Cursor catalog entry
    cursor_entry = next(c for c in catalog if c["id"] == "cursor")
    assert cursor_entry["label"] == "Cursor"
    assert "auto" in [m["id"] for m in cursor_entry["models"]]


def test_model_catalog_shows_only_latest_models_for_all_providers():
    """Verify that all providers only expose latest generation models and omit legacy/outdated models."""
    catalog = {c["id"]: [m["id"] for m in c["models"]] for c in get_model_catalog()}

    # OpenAI: only GPT-5.6 / GPT-6 / o3; no legacy GPT-4, GPT-4o, o1
    assert "gpt-5.6-terra" in catalog["openai"]
    assert "gpt-6-astra" in catalog["openai"]
    assert "gpt-4o" not in catalog["openai"]
    assert "gpt-4o-mini" not in catalog["openai"]
    assert "o1" not in catalog["openai"]

    # Claude: current generation only. The 3.x '-latest' aliases reached
    # end-of-life on 2026-02-19 and no longer resolve.
    assert "claude-opus-5" in catalog["claude"]
    assert "claude-sonnet-5" in catalog["claude"]
    assert "claude-3-opus-latest" not in catalog["claude"]
    assert "claude-3-7-sonnet-latest" not in catalog["claude"]
    assert "claude-3-5-sonnet-latest" not in catalog["claude"]

    # Gemini: only Gemini 2.5 and 2.0; no old Gemini 1.5
    assert "gemini-2.5-flash" in catalog["gemini"]
    assert "gemini-2.5-pro" in catalog["gemini"]
    assert "gemini-1.5-pro" not in catalog["gemini"]
    assert "gemini-1.5-flash" not in catalog["gemini"]

    # xAI: current Grok 4.x only; the Grok 2/3 ids were retired upstream
    assert "grok-4.6" in catalog["xai"]
    assert "grok-beta" not in catalog["xai"]
    assert "grok-3" not in catalog["xai"]
    assert "grok-2-1212" not in catalog["xai"]

    # Cursor: ids must be ones its CLI accepts (`agent --list-models`).
    # cursor-fast / cursor-small / claude-sonnet-5 were invented and rejected.
    assert "auto" in catalog["cursor"]
    assert "cursor-fast" not in catalog["cursor"]
    assert "cursor-small" not in catalog["cursor"]
    assert "claude-sonnet-5" not in catalog["cursor"]

    # OpenRouter: current Claude & GPT generation
    assert "anthropic/claude-sonnet-5" in catalog["openrouter"]
    assert "anthropic/claude-3.7-sonnet" not in catalog["openrouter"]
    assert "openai/gpt-5.6-terra" in catalog["openrouter"]
    assert "anthropic/claude-3.5-sonnet" not in catalog["openrouter"]
    assert "openai/gpt-4o" not in catalog["openrouter"]

    # Ollama: only returns installed modern models or latest fallback; never old llama3.1
    assert "llama3.1" not in catalog["ollama"]
    assert any("llama3.2" in m or "llama3.3" in m or "qwen" in m for m in catalog["ollama"])


def test_context_window_lookup():
    """Verify approximate context window mappings."""
    assert context_window("gemini-2.5-pro") == 1_000_000
    assert context_window("claude-3-7-sonnet-latest") == 200_000
    assert context_window("grok-4.6") == 131_072
    assert context_window("deepseek-chat") == 64_000
    assert context_window("cursor-small") == 128_000


def test_gemini_provider_chat():
    """Test Gemini provider OpenAI-compatible chat response and tool call handling."""
    p = GeminiProvider(api_key="fake-gemini-key")
    ready, why = p.is_ready()
    assert ready is True

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Here is the summary.",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "search_brain",
                                "arguments": json.dumps({"query": "projects"}),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 18},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        res = p.chat(
            [Message(role="user", content="What projects am I working on?")],
            tools=[Tool(name="search_brain", description="Search brain", parameters={})],
        )
        assert res.text == "Here is the summary."
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "search_brain"
        assert res.tool_calls[0].arguments == {"query": "projects"}
        assert res.input_tokens == 42
        assert res.output_tokens == 18

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer fake-gemini-key"


def test_xai_provider_chat():
    """Test xAI Grok provider chat execution."""
    p = XAIProvider(api_key="fake-xai-key")
    ready, _ = p.is_ready()
    assert ready is True

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Grok answering your request.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        res = p.chat([Message(role="user", content="Hello Grok")])
        assert res.text == "Grok answering your request."
        assert res.input_tokens == 20
        assert res.output_tokens == 10
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.x.ai/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer fake-xai-key"


def test_cursor_provider_runs_through_the_cli():
    """Cursor has no chat-completions endpoint — verified 2026-09-12:
    `POST api.cursor.com/v1/chat/completions` returns 404 Route not found.
    Models run through the headless CLI (`agent -p`) instead."""
    from unittest.mock import patch

    with patch("lodestone.models.cursor.find_cursor_cli", return_value=None):
        p = CursorProvider()
        assert p.model == "auto"
        ready, reason = p.is_ready()
        # An API key alone cannot help: there is no endpoint to send it to.
        assert ready is False
        assert "CLI" in reason

    with patch("lodestone.models.cursor.find_cursor_cli", return_value="/usr/bin/agent"):
        assert CursorProvider().is_ready() == (True, "")

    assert not hasattr(CursorProvider(), "base_url"), \
        "Cursor must not be modelled as an OpenAI-compatible HTTP provider"


def test_deepseek_provider():
    """Test DeepSeek provider initialization and readiness check."""
    p_unready = DeepSeekProvider(api_key="")
    ready, why = p_unready.is_ready()
    assert ready is False
    assert "DEEPSEEK_API_KEY" in why

    p_ready = DeepSeekProvider(api_key="fake-deepseek-key")
    ready, _ = p_ready.is_ready()
    assert ready is True
    assert p_ready.default_base == "https://api.deepseek.com/v1"


def test_provider_test_endpoint():
    """Verify POST /api/providers/{name}/test endpoint."""
    from fastapi.testclient import TestClient
    from lodestone.api.app import app

    client = TestClient(app)

    # Test with unready provider / empty key
    resp = client.post("/api/providers/gemini/test", json={"value": ""})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False

    # Test with valid dummy key
    resp = client.post("/api/providers/gemini/test", json={"value": "AIzaSyTestKey123"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

