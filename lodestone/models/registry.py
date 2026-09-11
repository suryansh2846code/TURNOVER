"""Provider registry — resolves the configured 'bring your own model' backend.

Turnstone lets you bring a model four ways; this mirrors that:
  1. subscription  -> your paid ChatGPT/Claude/Cursor session, via a local
                      OpenAI-compatible gateway (LODESTONE_SUBSCRIPTION_BASE_URL).
  2. api-key        -> anthropic / openai (your own key).
  3. openrouter     -> hundreds of models behind one key.
  4. ollama         -> free local open-source models, fully offline.
A `mock` provider keeps the whole agent stack testable with no network/keys.
"""
from __future__ import annotations

import os
import re
import uuid
from functools import lru_cache

from ..config import get_settings
from .anthropic import AnthropicProvider
from .base import ChatResult, LLMProvider, Message, ToolCall
from .claude_code import ClaudeCodeProvider
from .cursor import CursorProvider
from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider
from .openai_compat import OllamaProvider, OpenAICompatProvider, OpenRouterProvider
from .xai import XAIProvider


class SubscriptionProvider(OpenAICompatProvider):
    """Use an existing paid subscription (ChatGPT/Claude/Cursor) via a local
    OpenAI-compatible gateway that holds your session — no API key billing.

    Point LODESTONE_SUBSCRIPTION_BASE_URL at the gateway (e.g. a local
    subscription proxy). This is the hard, ToS-sensitive path Turnstone
    advertises; Lodestone treats it as a pluggable gateway rather than
    reverse-engineering each vendor's private auth.
    """
    name = "subscription"
    default_base = "http://localhost:8080/v1"
    default_model = "claude-sonnet-5"
    key_env = "LODESTONE_SUBSCRIPTION_KEY"
    key_required = False

    def is_ready(self) -> tuple[bool, str]:
        base = os.environ.get("LODESTONE_SUBSCRIPTION_BASE_URL")
        if not base:
            return False, "set LODESTONE_SUBSCRIPTION_BASE_URL to your subscription gateway"
        self.base_url = base.rstrip("/")
        return True, ""


class MockProvider(LLMProvider):
    """Deterministic offline provider. Calls search_brain once, then answers
    from the tool result — enough to exercise the full agent tool loop with no
    network or API key."""
    name = "mock"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or "mock-1"

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        last = messages[-1]
        tool_names = {t.name for t in (tools or [])}
        # If we just got a tool result, produce a final answer from it.
        if last.role == "tool":
            return ChatResult(text=f"Based on your brain: {last.content[:400]}")
        # Otherwise, if a brain-search tool exists and we haven't used it, do so.
        already = any(m.role == "tool" for m in messages)
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "search_brain" in tool_names and not already:
            return ChatResult(text="", tool_calls=[ToolCall(
                id=str(uuid.uuid4()), name="search_brain",
                arguments={"query": user[:120] or "context"},
            )])
        return ChatResult(text=f"(mock) You said: {user[:200]}")


_REGISTRY: dict[str, type[LLMProvider]] = {
    "claude": AnthropicProvider,
    "anthropic": AnthropicProvider,
    "claude-code": ClaudeCodeProvider,
    "cursor": CursorProvider,
    "gemini": GeminiProvider,
    "google": GeminiProvider,
    "xai": XAIProvider,
    "grok": XAIProvider,
    "openai": OpenAICompatProvider,
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "subscription": SubscriptionProvider,
    "mock": MockProvider,
}


# Canonical provider keys (deduplicating aliases for catalog & UI presentation)
PRIMARY_PROVIDERS = [
    "claude",
    "cursor",
    "gemini",
    "xai",
    "openai",
    "deepseek",
    "ollama",
    "openrouter",
    "claude-code",
    "subscription",
    "mock",
]


# Where each backend sends your context at query time. "local" = stays on your
# Mac; "cloud" = the injected brain context is sent off-device to that service.
_LOCALITY = {
    "mock":         ("local", "Nothing leaves your Mac (offline)."),
    "ollama":       ("local", "Runs on your Mac — your context stays on-device."),
    "cursor":       ("local", "Connects to your local Cursor session bridge or API."),
    "claude-code":  ("cloud", "Sent to Anthropic through the Claude CLI."),
    "claude":       ("cloud", "Sent to Anthropic's API."),
    "anthropic":    ("cloud", "Sent to Anthropic's API."),
    "gemini":       ("cloud", "Sent to Google Gemini API."),
    "google":       ("cloud", "Sent to Google Gemini API."),
    "xai":          ("cloud", "Sent to xAI Grok API."),
    "grok":         ("cloud", "Sent to xAI Grok API."),
    "openai":       ("cloud", "Sent to OpenAI's API."),
    "deepseek":     ("cloud", "Sent to DeepSeek's API."),
    "openrouter":   ("cloud", "Sent to OpenRouter (and the chosen model's host)."),
    "subscription": ("cloud", "Sent via your gateway to the model provider."),
}

# approximate context windows (tokens) by model-name substring — the only "limit"
# we can know without a provider account API; matched loosely, shown as approximate.
_CONTEXT_WINDOW = {
    "opus": 200_000, "sonnet": 200_000, "haiku": 200_000, "claude": 200_000,
    "gpt-5": 400_000, "gpt-4o": 128_000, "gpt-4.1": 1_000_000, "gpt-4": 128_000,
    "o1": 200_000, "o3": 200_000, "o4": 200_000, "gemini": 1_000_000,
    "grok": 131_072, "cursor": 128_000,
    "llama": 128_000, "qwen": 32_000, "mistral": 32_000, "deepseek": 64_000,
}


MODEL_CATALOG = {
    "claude": {
        "id": "claude",
        "label": "Claude (Anthropic)",
        "icon": "spark",
        "default_model": "claude-3-7-sonnet-latest",
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            {"id": "claude-3-7-sonnet-latest", "name": "Claude 3.7 Sonnet", "desc": "Hybrid reasoning & coding flagship"},
            {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet", "desc": "High-intelligence workhorse"},
            {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "desc": "Fast & responsive everyday model"},
            {"id": "claude-3-opus-latest", "name": "Claude 3 Opus", "desc": "Complex long-form analysis"},
        ],
    },
    "cursor": {
        "id": "cursor",
        "label": "Cursor",
        "icon": "terminal",
        "default_model": "cursor-small",
        "key_env": "CURSOR_API_KEY",
        "key_url": "https://cursor.com",
        "models": [
            {"id": "cursor-small", "name": "Cursor Small", "desc": "Fast local coding & agent flow"},
            {"id": "cursor-fast", "name": "Cursor Fast", "desc": "Low latency reasoning"},
            {"id": "claude-3.5-sonnet", "name": "Cursor Claude 3.5 Sonnet", "desc": "Via Cursor session bridge"},
            {"id": "gpt-4o", "name": "Cursor GPT-4o", "desc": "Via Cursor session bridge"},
        ],
    },
    "gemini": {
        "id": "gemini",
        "label": "Google Gemini",
        "icon": "globe",
        "default_model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "desc": "Next-gen speed, reasoning & multimodal"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "desc": "Deep reasoning across complex domains"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "desc": "Ultra-fast generation & tool use"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "desc": "2-million token massive context"},
            {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "desc": "Lightweight & cost-effective"},
        ],
    },
    "xai": {
        "id": "xai",
        "label": "xAI (Grok)",
        "icon": "zap",
        "default_model": "grok-2-1212",
        "key_env": "XAI_API_KEY",
        "key_url": "https://console.x.ai",
        "models": [
            {"id": "grok-2-1212", "name": "Grok 2 (1212)", "desc": "Advanced reasoning & tool calling"},
            {"id": "grok-2-vision-1212", "name": "Grok 2 Vision", "desc": "Multimodal reasoning & image understanding"},
            {"id": "grok-beta", "name": "Grok Beta", "desc": "Latest experimental capabilities"},
        ],
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "icon": "spark",
        "default_model": "gpt-4o",
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "desc": "Omni flagship for general tasks"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "desc": "Fast, affordable intelligence"},
            {"id": "o1", "name": "o1", "desc": "Advanced deliberate reasoning"},
            {"id": "o3-mini", "name": "o3-mini", "desc": "Fast STEM & code reasoning"},
        ],
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "icon": "chip",
        "default_model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek V3", "desc": "Elite coding & general intelligence"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1", "desc": "Reasoning model with chain of thought"},
        ],
    },
    "ollama": {
        "id": "ollama",
        "label": "Ollama (Local)",
        "icon": "laptop",
        "default_model": "llama3.2",
        "key_env": "",
        "key_url": "https://ollama.com",
        "models": [
            {"id": "llama3.2", "name": "Llama 3.2", "desc": "Compact offline local model"},
            {"id": "llama3.1", "name": "Llama 3.1", "desc": "Balanced local model"},
            {"id": "qwen2.5:7b", "name": "Qwen 2.5 (7B)", "desc": "Strong multilingual & coding local model"},
            {"id": "deepseek-r1:8b", "name": "DeepSeek R1 (8B)", "desc": "Local reasoning model"},
        ],
    },
    "openrouter": {
        "id": "openrouter",
        "label": "OpenRouter",
        "icon": "router",
        "default_model": "anthropic/claude-3.5-sonnet",
        "key_env": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "desc": "Via OpenRouter"},
            {"id": "openai/gpt-4o", "name": "GPT-4o", "desc": "Via OpenRouter"},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "desc": "Via OpenRouter"},
            {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "desc": "Via OpenRouter"},
        ],
    },
    "claude-code": {
        "id": "claude-code",
        "label": "Claude Code CLI",
        "icon": "terminal",
        "default_model": "claude-code",
        "key_env": "",
        "key_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        "models": [
            {"id": "claude-code", "name": "Claude Code Session", "desc": "Local Anthropic CLI bridge"},
        ],
    },
    "subscription": {
        "id": "subscription",
        "label": "Subscription Gateway",
        "icon": "key",
        "default_model": "subscription",
        "key_env": "LODESTONE_SUBSCRIPTION_KEY",
        "key_url": "",
        "models": [
            {"id": "subscription", "name": "Subscription Proxy", "desc": "Local proxy for paid sessions"},
        ],
    },
    "mock": {
        "id": "mock",
        "label": "Mock (Offline)",
        "icon": "box",
        "default_model": "mock-1",
        "key_env": "",
        "key_url": "",
        "models": [
            {"id": "mock-1", "name": "Mock Test Model", "desc": "Offline deterministic test fixture"},
        ],
    },
}


def context_window(model: str | None) -> int | None:
    if not model:
        return None
    m = model.lower()
    for k, v in _CONTEXT_WINDOW.items():
        if k in m:
            return v
    return None


from .capabilities import get_capabilities
from .connections import ConnectionStatus, get_connection, save_connection
from .discovery import get_discovered_models


def get_model_catalog(force_refresh: bool = False) -> list[dict]:
    """Return unified model catalog for UI and per-agent configuration."""
    catalog = []
    for pid in PRIMARY_PROVIDERS:
        entry = MODEL_CATALOG.get(pid)
        if not entry:
            continue
        cls = _REGISTRY.get(pid)
        ready = False
        reason = ""
        if cls:
            try:
                ready, reason = cls().is_ready()
            except Exception as exc:
                ready, reason = False, str(exc)

        # Dynamic model discovery & account metadata
        models, account_meta = get_discovered_models(pid, force_refresh=force_refresh)
        if not models:
            models = entry.get("models", [])

        # Connection state & capabilities
        conn = get_connection(pid)
        caps = get_capabilities(pid)

        # Sync readiness into connection if ready changed
        if ready and conn.connection_status == ConnectionStatus.NOT_CONNECTED:
            conn.connection_status = ConnectionStatus.API_KEY_CONNECTED if caps and caps.api_key_supported else ConnectionStatus.CONNECTED

        locality, destination = _LOCALITY.get(pid, ("cloud", "Sent to model provider."))
        catalog.append({
            "id": entry["id"],
            "label": entry["label"],
            "icon": entry.get("icon", "spark"),
            "default_model": entry["default_model"],
            "key_env": entry.get("key_env", ""),
            "key_url": entry.get("key_url", ""),
            "models": models,
            "ready": ready,
            "reason": reason,
            "locality": locality,
            "destination": destination,
            "capabilities": caps.to_dict() if caps else None,
            "connection": conn.to_dict(),
            "account_meta": account_meta,
        })
    return catalog


def list_providers() -> list[dict]:
    out = []
    try:
        from .accounts import detect_all_accounts
        local_accounts = detect_all_accounts()
    except Exception:
        local_accounts = {}

    # Show primary providers in deterministic order
    for name in PRIMARY_PROVIDERS:
        cls = _REGISTRY.get(name)
        if not cls:
            continue
        try:
            ready, reason = cls().is_ready()
        except Exception as exc:
            ready, reason = False, str(exc)
        locality, destination = _LOCALITY.get(name, ("cloud", "Sent to the model provider."))
        conn = get_connection(name)

        acct = local_accounts.get(name)
        if acct and acct.get("found_on_computer"):
            if name == "gemini" and acct.get("connected") and conn.connection_status not in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.DISCONNECTED):
                conn.email = acct.get("email")
                conn.auth_method = "account"
                conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
                conn.status_message = "Connected to Google Gemini"
                save_connection(conn)
                ready = True
                reason = ""

        caps = get_capabilities(name)
        out.append({
            "name": name,
            "ready": ready,
            "reason": reason,
            "locality": locality,
            "destination": destination,
            "connection": conn.to_dict(),
            "capabilities": caps.to_dict() if caps else None,
            "detected_account": acct if (acct and acct.get("found_on_computer")) else None,
        })
    return out


def clear_provider_cache() -> None:
    """Clear cached provider instances so new keys/endpoints take effect immediately."""
    get_provider.cache_clear()


@lru_cache
def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    name = (name or get_settings().model_provider or "mock").lower()
    cls = _REGISTRY.get(name, MockProvider)
    p = cls(model=model)
    _wrap_usage(p)
    return p


def _wrap_usage(p: LLMProvider) -> None:
    """Wrap chat() so every model call records token usage centrally (choke point
    for enrichment, chat, digest, welcome…). Estimates from length when the
    provider doesn't report usage (Claude CLI, subscription, mock)."""
    orig = p.chat

    def chat(messages, **kw):
        r = orig(messages, **kw)
        try:
            from ..usage import record
            tin, tout = getattr(r, "input_tokens", 0), getattr(r, "output_tokens", 0)
            if tin == 0 and tout == 0:
                tin = sum(len(getattr(m, "content", "") or "") for m in messages) // 4
                tout = len(getattr(r, "text", "") or "") // 4
            record(p.name, getattr(p, "model", None), tin, tout)
        except Exception:
            pass
        return r

    p.chat = chat
