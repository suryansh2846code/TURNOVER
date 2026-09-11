"""Unit tests for the Universal Provider Plan & Model Entitlement Engine."""
from __future__ import annotations

from lodestone.models.entitlements import (
    evaluate_model_entitlement,
    get_best_unlocked_model,
    is_provider_connected,
    normalize_plan_tier,
    OPENAI_TIER_FREE,
    OPENAI_TIER_PLUS,
    OPENAI_TIER_PRO,
    CLAUDE_TIER_FREE,
    CLAUDE_TIER_PRO,
    CURSOR_TIER_FREE,
    CURSOR_TIER_PRO,
)


def test_unconnected_providers_are_locked():
    """Verify that any unconnected provider locks all its models with 'Connect in Models'."""
    # OpenRouter not connected
    locked, req = evaluate_model_entitlement("openrouter", "anthropic/claude-3.7-sonnet", is_connected=False)
    assert locked is True
    assert req == "Connect in Models"

    # DeepSeek not connected
    locked, req = evaluate_model_entitlement("deepseek", "deepseek-chat", is_connected=False)
    assert locked is True
    assert req == "Connect in Models"

    # Ollama offline / not connected
    locked, req = evaluate_model_entitlement("ollama", "llama3.2", is_connected=False)
    assert locked is True
    assert req == "Connect in Models"

    # Claude not connected
    locked, req = evaluate_model_entitlement("claude", "claude-opus-5", is_connected=False)
    assert locked is True
    assert req == "Connect in Models"


def test_connected_openrouter_and_deepseek_unlock():
    """Verify connecting OpenRouter or DeepSeek unlocks their models."""
    locked, req = evaluate_model_entitlement("openrouter", "anthropic/claude-3.7-sonnet", is_connected=True)
    assert locked is False
    assert req is None

    locked, req = evaluate_model_entitlement("deepseek", "deepseek-chat", is_connected=True)
    assert locked is False
    assert req is None


def test_ollama_installed_vs_uninstalled():
    """Verify connected Ollama checks installed tags dynamically."""
    installed = {"llama3.2:latest", "qwen2.5:3b"}

    # Installed model -> unlocked
    locked, req = evaluate_model_entitlement(
        "ollama", "llama3.2:latest", is_connected=True, context={"installed_models": installed}
    )
    assert locked is False
    assert req is None

    # Base name match -> unlocked
    locked, req = evaluate_model_entitlement(
        "ollama", "llama3.2", is_connected=True, context={"installed_models": installed}
    )
    assert locked is False
    assert req is None

    # Uninstalled model -> locked with Pull required
    locked, req = evaluate_model_entitlement(
        "ollama", "llama3.3:70b", is_connected=True, context={"installed_models": installed}
    )
    assert locked is True
    assert req == "Pull required"


def test_openai_plan_entitlements_for_any_user():
    """Verify OpenAI models lock and unlock strictly according to any user's plan."""
    # Free tier
    locked, req = evaluate_model_entitlement("openai", "gpt-5.6-terra", is_connected=True, user_plan="ChatGPT Free")
    assert locked is False

    locked, req = evaluate_model_entitlement("openai", "gpt-6-astra", is_connected=True, user_plan="ChatGPT Free")
    assert locked is True
    assert req == "Pro"

    locked, req = evaluate_model_entitlement("openai", "o3-mini", is_connected=True, user_plan="ChatGPT Free")
    assert locked is True
    assert req == "Plus"

    # Plus tier
    locked, req = evaluate_model_entitlement("openai", "o3-mini", is_connected=True, user_plan="ChatGPT Plus")
    assert locked is False

    locked, req = evaluate_model_entitlement("openai", "gpt-6-astra", is_connected=True, user_plan="ChatGPT Plus")
    assert locked is True
    assert req == "Pro"

    # Pro / Team / Enterprise tier
    for plan in ("ChatGPT Pro", "ChatGPT Team", "ChatGPT Enterprise"):
        locked, _ = evaluate_model_entitlement("openai", "gpt-6-astra", is_connected=True, user_plan=plan)
        assert locked is False
        locked, _ = evaluate_model_entitlement("openai", "gpt-5.6-sol", is_connected=True, user_plan=plan)
        assert locked is False
        locked, _ = evaluate_model_entitlement("openai", "gpt-5.6-terra", is_connected=True, user_plan=plan)
        assert locked is False


def test_claude_plan_entitlements_for_any_user():
    """Verify Claude models lock and unlock strictly according to any user's plan."""
    # Free tier
    locked, req = evaluate_model_entitlement("claude", "claude-3-7-sonnet", is_connected=True, user_plan="Claude Free")
    assert locked is False

    locked, req = evaluate_model_entitlement("claude", "claude-opus-5", is_connected=True, user_plan="Claude Free")
    assert locked is True
    assert req == "Pro"

    # Pro tier
    locked, req = evaluate_model_entitlement("claude", "claude-opus-5", is_connected=True, user_plan="Claude Pro")
    assert locked is False
    assert req is None

    locked, req = evaluate_model_entitlement("claude", "claude-sonnet-5", is_connected=True, user_plan="Claude Pro")
    assert locked is False

    # Disabled flag from session cache
    context = {"disabled_models": {"fable": "Update to CLI 2.1.255+ required"}}
    locked, req = evaluate_model_entitlement(
        "claude", "claude-fable-5-1", is_connected=True, user_plan="Claude Pro", context=context
    )
    assert locked is True
    assert "2.1.255" in (req or "")


def test_cursor_plan_entitlements_for_any_user():
    """Verify Cursor models lock and unlock strictly according to any user's membership."""
    # Free membership
    locked, req = evaluate_model_entitlement("cursor", "cursor-fast", is_connected=True, user_plan="Cursor Free")
    assert locked is False

    locked, req = evaluate_model_entitlement("cursor", "claude-opus-5", is_connected=True, user_plan="Cursor Free")
    assert locked is True
    assert req == "Pro"

    locked, req = evaluate_model_entitlement("cursor", "gpt-5.6-terra", is_connected=True, user_plan="Cursor Free")
    assert locked is True
    assert req == "Pro"

    # Pro membership
    locked, req = evaluate_model_entitlement("cursor", "claude-opus-5", is_connected=True, user_plan="Cursor Pro")
    assert locked is False
    assert req is None

    locked, req = evaluate_model_entitlement("cursor", "gpt-5.6-terra", is_connected=True, user_plan="Cursor Pro")
    assert locked is False
    assert req is None


def test_get_best_unlocked_model_auto_selection():
    """Verify auto-picker selects the best model available on that specific user's tier."""
    models = ["gpt-6-astra", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"]

    # Free user gets gpt-5.6-terra (since Astra is locked)
    best_free = get_best_unlocked_model("openai", models, is_connected=True, user_plan="ChatGPT Free")
    assert best_free == "gpt-5.6-terra"

    # Pro user gets gpt-6-astra (unlocked for them)
    best_pro = get_best_unlocked_model("openai", models, is_connected=True, user_plan="ChatGPT Pro")
    assert best_pro == "gpt-6-astra"

    # Unconnected provider has no best unlocked model
    best_unconnected = get_best_unlocked_model("openai", models, is_connected=False, user_plan="ChatGPT Pro")
    assert best_unconnected is None
