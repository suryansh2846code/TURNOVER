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
from .openai_compat import OllamaProvider, OpenAICompatProvider, OpenRouterProvider


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
    model = "mock-1"

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
    "claude-code": ClaudeCodeProvider,
    "subscription": SubscriptionProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAICompatProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "mock": MockProvider,
}


# Where each backend sends your context at query time. "local" = stays on your
# Mac; "cloud" = the injected brain context is sent off-device to that service.
_LOCALITY = {
    "mock":         ("local", "Nothing leaves your Mac (offline)."),
    "ollama":       ("local", "Runs on your Mac — your context stays on-device."),
    "claude-code":  ("cloud", "Sent to Anthropic through the Claude CLI."),
    "anthropic":    ("cloud", "Sent to Anthropic's API."),
    "openai":       ("cloud", "Sent to OpenAI's API."),
    "openrouter":   ("cloud", "Sent to OpenRouter (and the chosen model's host)."),
    "subscription": ("cloud", "Sent via your gateway to the model provider."),
}

# approximate context windows (tokens) by model-name substring — the only "limit"
# we can know without a provider account API; matched loosely, shown as approximate.
_CONTEXT_WINDOW = {
    "opus": 200_000, "sonnet": 200_000, "haiku": 200_000, "claude": 200_000,
    "gpt-5": 400_000, "gpt-4o": 128_000, "gpt-4.1": 1_000_000, "gpt-4": 128_000,
    "o1": 200_000, "o3": 200_000, "o4": 200_000, "gemini": 1_000_000,
    "llama": 128_000, "qwen": 32_000, "mistral": 32_000, "deepseek": 64_000,
}


def context_window(model: str | None) -> int | None:
    if not model:
        return None
    m = model.lower()
    for k, v in _CONTEXT_WINDOW.items():
        if k in m:
            return v
    return None


def list_providers() -> list[dict]:
    out = []
    for name, cls in _REGISTRY.items():
        try:
            ready, reason = cls().is_ready()
        except Exception as exc:
            ready, reason = False, str(exc)
        locality, destination = _LOCALITY.get(name, ("cloud", "Sent to the model provider."))
        out.append({"name": name, "ready": ready, "reason": reason,
                    "locality": locality, "destination": destination})
    return out


@lru_cache
def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    name = (name or get_settings().model_provider or "mock").lower()
    cls = _REGISTRY.get(name, MockProvider)
    p = cls(model=model) if name != "mock" else cls()
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
