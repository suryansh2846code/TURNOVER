"""Unit tests for Provider Capabilities registry."""
from __future__ import annotations

from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.models.capabilities import (
    CAPABILITIES_REGISTRY,
    get_capabilities,
)


def test_capabilities_registry_values():
    """Verify that capabilities registry reflects authentic provider capabilities."""
    # OpenAI: API key and ChatGPT OAuth PKCE / Codex CLI support
    openai_caps = get_capabilities("openai")
    assert openai_caps is not None
    assert openai_caps.api_key_supported is True
    assert openai_caps.oauth_supported is True
    assert openai_caps.local_cli_auth_supported is True
    assert openai_caps.account_identity_supported is True
    assert openai_caps.model_discovery_supported is True

    # xAI: API key only, no fake OAuth
    xai_caps = get_capabilities("xai")
    assert xai_caps is not None
    assert xai_caps.api_key_supported is True
    assert xai_caps.oauth_supported is False
    assert xai_caps.model_discovery_supported is True

    # DeepSeek: API key only, no fake OAuth
    ds_caps = get_capabilities("deepseek")
    assert ds_caps is not None
    assert ds_caps.api_key_supported is True
    assert ds_caps.oauth_supported is False

    # Gemini: API key only, no OAuth
    gem_caps = get_capabilities("gemini")
    assert gem_caps is not None
    assert gem_caps.api_key_supported is True
    assert gem_caps.oauth_supported is False
    assert gem_caps.account_identity_supported is False

    # OpenRouter: API key only — no OAuth flow is implemented, and claiming one
    # rendered a "Sign in with OpenRouter" button that did nothing.
    or_caps = get_capabilities("openrouter")
    assert or_caps is not None
    assert or_caps.api_key_supported is True
    assert or_caps.oauth_supported is False
    assert or_caps.api_key_only is True

    # Ollama: Local daemon, no account or API key required
    ollama_caps = get_capabilities("ollama")
    assert ollama_caps is not None
    assert ollama_caps.api_key_supported is False
    assert ollama_caps.oauth_supported is False
    assert ollama_caps.local_cli_auth_supported is True
    assert ollama_caps.model_discovery_supported is True

    # Claude Code: Local CLI bridge
    cc_caps = get_capabilities("claude-code")
    assert cc_caps is not None
    assert cc_caps.local_cli_auth_supported is True


def test_capabilities_alias_resolution():
    """Verify provider aliases resolve correctly to canonical capabilities."""
    assert get_capabilities("anthropic") == get_capabilities("claude")
    assert get_capabilities("google") == get_capabilities("gemini")
    assert get_capabilities("grok") == get_capabilities("xai")


def test_capabilities_api_endpoint():
    """Verify GET /api/providers/capabilities endpoint."""
    client = TestClient(app)
    resp = client.get("/api/providers/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "capabilities" in data
    caps = data["capabilities"]
    assert len(caps) >= 8
    pids = [c["provider_id"] for c in caps]
    for p in ("claude", "cursor", "gemini", "xai", "openai", "deepseek", "ollama", "openrouter"):
        assert p in pids


# ── a capability may not advertise a flow that does not exist ────────────
def test_advertised_sign_ins_are_actually_implemented():
    """`has_interactive_signin` promises a control the user can press. Every
    provider claiming one must resolve to a flow that really starts something."""
    from lodestone.models.auth_flows import ApiKeyOnlyFlow, get_flow

    for pid, caps in CAPABILITIES_REGISTRY.items():
        flow = get_flow(pid)
        if caps.has_interactive_signin:
            assert not isinstance(flow, ApiKeyOnlyFlow), (
                f"{pid} advertises a sign-in but resolves to ApiKeyOnlyFlow")
        if caps.api_key_only:
            assert isinstance(flow, ApiKeyOnlyFlow), (
                f"{pid} is key-only but resolves to {type(flow).__name__}")


def test_api_key_only_and_interactive_signin_are_mutually_exclusive():

    for pid, caps in CAPABILITIES_REGISTRY.items():
        assert not (caps.api_key_only and caps.has_interactive_signin), pid
