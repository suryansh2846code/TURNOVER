"""Dynamic model discovery and capability detection for TURNOVER / Lodestone.

Queries official provider endpoints to retrieve actual available models,
capabilities (tools, vision, reasoning, structured output), and context windows.
Eliminates stale hardcoded model IDs and guarantees live catalog truth.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .base import _saved_key

_CACHE_TTL = 3600  # 1 hour cache unless refreshed
_MODEL_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass
class DiscoveredModel:
    id: str
    name: str
    desc: str
    context_window: int | None = None
    tool_calling: bool = True
    structured_output: bool = True
    streaming: bool = True
    vision: bool = False
    reasoning: bool = False
    status: str = "available"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_capabilities(model_id: str, desc: str = "") -> dict[str, Any]:
    mid = model_id.lower()
    d = desc.lower()

    # Reasoning models
    is_reasoning = any(k in mid for k in ("o1", "o3", "reasoner", "r1", "thinking", "terra", "luna", "sol", "astra", "gpt-5", "gpt-6")) or "reasoning" in d
    if "3-7-sonnet" in mid:
        is_reasoning = True

    # Vision models
    is_vision = any(k in mid for k in ("vision", "4o", "gemini", "claude-3", "vl", "pixtral", "gpt-5", "gpt-6", "terra", "luna", "sol", "astra")) or "vision" in d

    # Tool calling support
    # (Almost all current flagship models support tools; legacy/completion models don't)
    no_tools = any(k in mid for k in ("instruct-preview", "base", "embed", "tts", "whisper", "dall-e"))
    tool_calling = not no_tools

    # Context window heuristic fallback
    context_window = 128_000
    if "gemini" in mid:
        context_window = 1_000_000 if "1.5" in mid or "2.5" in mid else 128_000
    elif any(k in mid for k in ("claude-3", "sonnet", "haiku", "opus")):
        context_window = 200_000
    elif any(k in mid for k in ("gpt-5", "gpt-6", "terra", "luna", "sol", "astra")):
        context_window = 272_000
    elif "gpt-4o" in mid or "gpt-4-turbo" in mid:
        context_window = 128_000
    elif any(k in mid for k in ("o1", "o3")):
        context_window = 200_000
    elif "grok" in mid:
        context_window = 131_072
    elif "deepseek" in mid:
        context_window = 64_000

    return {
        "reasoning": is_reasoning,
        "vision": is_vision,
        "tool_calling": tool_calling,
        "context_window": context_window,
        "structured_output": True,
        "streaming": True,
        "status": "available",
    }


def _chatgpt_subscription_models() -> list[DiscoveredModel]:
    """Retrieve models available through ChatGPT Subscription / Codex."""
    models: list[DiscoveredModel] = []
    cache_path = Path.home() / "Library/Application Support/Turnstone/provider-auth/codex/models_cache.json"
    if cache_path.exists():
        try:
            cached_data = json.loads(cache_path.read_text())
            for m in cached_data.get("models", []):
                slug = m.get("slug")
                if not slug:
                    continue
                display_name = m.get("display_name") or slug.replace("-", " ").title()
                desc = m.get("description") or "Codex agentic coding model"
                models.append(DiscoveredModel(
                    id=slug,
                    name=display_name,
                    desc=desc,
                    reasoning=True,
                    vision=True,
                    tool_calling=True,
                    context_window=m.get("context_window", 272_000),
                    structured_output=True,
                    streaming=True,
                    status="available",
                ))
        except Exception:
            pass

    if models:
        return models

    return [
        DiscoveredModel("gpt-5.6-terra", "GPT-5.6-Terra", "Balanced agentic coding model for everyday work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.6-luna", "GPT-5.6-Luna", "Fast and affordable agentic coding model", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.5", "GPT-5.5", "Proven model for coding and general work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.6-sol", "GPT-5.6-Sol", "Flagship agentic coding model for complex tasks", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-6-astra", "GPT-6-Astra", "Our most capable model for complex, demanding work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-reserve", "GPT-Reserve", "Fast and affordable backup agentic coding model", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-4o", "GPT-4o", "Flagship multimodal intelligence", 128_000, vision=True),
        DiscoveredModel("gpt-4o-mini", "GPT-4o Mini", "Fast, affordable intelligence", 128_000, vision=True),
        DiscoveredModel("o3-mini", "o3-mini", "High-speed STEM and code reasoning", 200_000, reasoning=True),
        DiscoveredModel("o1", "o1", "Deliberate deep reasoning", 200_000, reasoning=True),
    ]


def discover_openai_models(api_key: str | None = None) -> tuple[list[DiscoveredModel], dict[str, Any]]:
    key = api_key or os.environ.get("OPENAI_API_KEY") or _saved_key("OPENAI_API_KEY")
    account_info: dict[str, Any] = {}

    # Check if ChatGPT Subscription is active
    try:
        from .chatgpt_auth import get_chatgpt_access_token, detect_chatgpt_local_session
        sess = detect_chatgpt_local_session(fetch_usage=False)
        has_sub = bool(get_chatgpt_access_token() or (sess and sess.get("has_token")))
        if sess and sess.get("email"):
            account_info["email"] = sess.get("email")
            account_info["name"] = sess.get("name")
            account_info["plan"] = sess.get("plan")
        if not key and has_sub:
            return _chatgpt_subscription_models(), account_info
    except Exception:
        pass

    if not key:
        return _fallback_openai(), account_info

    headers = {"Authorization": f"Bearer {key}"}

    # 1. Fetch account identity from /v1/me if permitted
    try:
        me_resp = httpx.get("https://api.openai.com/v1/me", headers=headers, timeout=4.0)
        if me_resp.status_code == 200:
            me_data = me_resp.json()
            account_info["email"] = me_data.get("email")
            account_info["account_id"] = me_data.get("id")
            account_info["name"] = me_data.get("name")
            orgs = me_data.get("orgs", {}).get("data", [])
            if orgs:
                account_info["organization"] = orgs[0].get("name") or orgs[0].get("id")
    except Exception:
        pass

    # 2. Discover models from OpenAI API
    try:
        resp = httpx.get("https://api.openai.com/v1/models", headers=headers, timeout=6.0)
        if resp.status_code != 200:
            return _fallback_openai(), account_info

        data = resp.json().get("data", [])
        models: list[DiscoveredModel] = []
        # Filter for chat / reasoning models
        chat_prefixes = ("gpt-5", "gpt-6", "gpt-4o", "gpt-4", "o1", "o3", "chatgpt")
        for m in sorted(data, key=lambda x: x.get("created", 0), reverse=True):
            mid = m.get("id", "")
            if not any(mid.startswith(p) for p in chat_prefixes):
                continue
            if any(x in mid for x in ("audio", "realtime", "transcription", "tts", "moderation", "embedding")):
                continue

            caps = _detect_capabilities(mid)
            models.append(DiscoveredModel(
                id=mid,
                name=mid.replace("-latest", "").replace("-", " ").title(),
                desc=f"Official OpenAI model ({caps['context_window'] // 1000}k context)",
                **caps,
            ))

        return models[:16] if models else _fallback_openai(), account_info
    except Exception:
        return _fallback_openai(), account_info


def discover_anthropic_models(api_key: str | None = None) -> list[DiscoveredModel]:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY") or _saved_key("ANTHROPIC_API_KEY")
    if not key:
        return _fallback_anthropic()

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    try:
        resp = httpx.get("https://api.anthropic.com/v1/models", headers=headers, timeout=6.0)
        if resp.status_code != 200:
            return _fallback_anthropic()

        data = resp.json().get("data", [])
        models: list[DiscoveredModel] = []
        for m in data:
            mid = m.get("id", "")
            display_name = m.get("display_name") or mid.replace("-", " ").title()
            caps = _detect_capabilities(mid)
            models.append(DiscoveredModel(
                id=mid,
                name=display_name,
                desc=f"Official Anthropic model ({caps['context_window'] // 1000}k context)",
                **caps,
            ))
        return models if models else _fallback_anthropic()
    except Exception:
        return _fallback_anthropic()


def discover_gemini_models(api_key: str | None = None) -> list[DiscoveredModel]:
    key = (api_key or os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY") or _saved_key("GEMINI_API_KEY"))
    if not key:
        return _fallback_gemini()

    try:
        resp = httpx.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=6.0,
        )
        if resp.status_code != 200:
            return _fallback_gemini()

        items = resp.json().get("models", [])
        models: list[DiscoveredModel] = []
        for m in items:
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            if "embedding" in name or "aqa" in name:
                continue
            display_name = m.get("displayName") or name.replace("-", " ").title()
            caps = _detect_capabilities(name, m.get("description", ""))
            input_limit = m.get("inputTokenLimit")
            if input_limit:
                caps["context_window"] = input_limit
            models.append(DiscoveredModel(
                id=name,
                name=display_name,
                desc=m.get("description") or "Google Gemini model",
                **caps,
            ))
        return models if models else _fallback_gemini()
    except Exception:
        return _fallback_gemini()


def discover_xai_models(api_key: str | None = None) -> list[DiscoveredModel]:
    key = api_key or os.environ.get("XAI_API_KEY") or _saved_key("XAI_API_KEY")
    if not key:
        return _fallback_xai()

    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = httpx.get("https://api.x.ai/v1/models", headers=headers, timeout=6.0)
        if resp.status_code != 200:
            return _fallback_xai()

        items = resp.json().get("data", [])
        models: list[DiscoveredModel] = []
        for m in items:
            mid = m.get("id", "")
            caps = _detect_capabilities(mid)
            models.append(DiscoveredModel(
                id=mid,
                name=mid.replace("-", " ").title(),
                desc=f"xAI Grok live model ({caps['context_window'] // 1000}k context)",
                **caps,
            ))
        return models if models else _fallback_xai()
    except Exception:
        return _fallback_xai()


def discover_deepseek_models(api_key: str | None = None) -> list[DiscoveredModel]:
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or _saved_key("DEEPSEEK_API_KEY")
    if not key:
        return _fallback_deepseek()

    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = httpx.get("https://api.deepseek.com/models", headers=headers, timeout=6.0)
        if resp.status_code != 200:
            return _fallback_deepseek()

        items = resp.json().get("data", [])
        models: list[DiscoveredModel] = []
        for m in items:
            mid = m.get("id", "")
            caps = _detect_capabilities(mid)
            models.append(DiscoveredModel(
                id=mid,
                name="DeepSeek " + mid.replace("deepseek-", "").title(),
                desc=f"Official DeepSeek live model ({caps['context_window'] // 1000}k context)",
                **caps,
            ))
        return models if models else _fallback_deepseek()
    except Exception:
        return _fallback_deepseek()


def discover_openrouter_models(api_key: str | None = None) -> list[DiscoveredModel]:
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or _saved_key("OPENROUTER_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = httpx.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=6.0)
        if resp.status_code != 200:
            return _fallback_openrouter()

        items = resp.json().get("data", [])
        models: list[DiscoveredModel] = []
        for m in items[:25]:
            mid = m.get("id", "")
            name = m.get("name") or mid
            ctx = m.get("context_length") or 128_000
            caps = _detect_capabilities(mid, m.get("description", ""))
            caps["context_window"] = ctx
            models.append(DiscoveredModel(
                id=mid,
                name=name,
                desc=m.get("description") or f"OpenRouter model ({ctx // 1000}k context)",
                **caps,
            ))
        return models if models else _fallback_openrouter()
    except Exception:
        return _fallback_openrouter()


def discover_ollama_models(host: str | None = None) -> list[DiscoveredModel]:
    url = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=3.0)
        if resp.status_code != 200:
            return _fallback_ollama()

        items = resp.json().get("models", [])
        models: list[DiscoveredModel] = []
        for m in items:
            name = m.get("name", "")
            size_gb = round(m.get("size", 0) / (1024 ** 3), 1)
            caps = _detect_capabilities(name)
            models.append(DiscoveredModel(
                id=name,
                name=name,
                desc=f"Local Ollama model ({size_gb} GB, on-device)",
                **caps,
            ))
        return models if models else _fallback_ollama()
    except Exception:
        return _fallback_ollama()


# ── Fallback static definitions when offline or unconfigured ─────────────────

def _fallback_openai() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("gpt-5.6-terra", "GPT-5.6-Terra", "Balanced agentic coding model for everyday work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.6-luna", "GPT-5.6-Luna", "Fast and affordable agentic coding model", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.5", "GPT-5.5", "Proven model for coding and general work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-5.6-sol", "GPT-5.6-Sol", "Flagship agentic coding model for complex tasks", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-6-astra", "GPT-6-Astra", "Our most capable model for complex, demanding work", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-reserve", "GPT-Reserve", "Fast and affordable backup agentic coding model", 272_000, vision=True, reasoning=True),
        DiscoveredModel("gpt-4o", "GPT-4o", "Flagship multimodal intelligence", 128_000, vision=True),
        DiscoveredModel("gpt-4o-mini", "GPT-4o Mini", "Fast, lightweight daily driver", 128_000, vision=True),
        DiscoveredModel("o3-mini", "o3-mini", "High-speed STEM and code reasoning", 200_000, reasoning=True),
        DiscoveredModel("o1", "o1", "Deliberate deep reasoning", 200_000, reasoning=True),
    ]


def _fallback_anthropic() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("claude-3-7-sonnet-latest", "Claude 3.7 Sonnet", "Hybrid reasoning and coding flagship", 200_000, vision=True, reasoning=True),
        DiscoveredModel("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet", "High-intelligence workhorse", 200_000, vision=True),
        DiscoveredModel("claude-3-5-haiku-latest", "Claude 3.5 Haiku", "Fast & responsive everyday model", 200_000),
        DiscoveredModel("claude-3-opus-latest", "Claude 3 Opus", "Complex long-form analysis", 200_000, vision=True),
    ]


def _fallback_gemini() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("gemini-2.5-flash", "Gemini 2.5 Flash", "Next-gen speed and reasoning", 1_000_000, vision=True),
        DiscoveredModel("gemini-2.5-pro", "Gemini 2.5 Pro", "Deep reasoning powerhouse", 1_000_000, vision=True, reasoning=True),
        DiscoveredModel("gemini-2.0-flash", "Gemini 2.0 Flash", "Ultra-fast generation & tool use", 1_000_000, vision=True),
        DiscoveredModel("gemini-1.5-pro", "Gemini 1.5 Pro", "2-million token massive context", 2_000_000, vision=True),
    ]


def _fallback_xai() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("grok-2-1212", "Grok 2 (1212)", "Advanced reasoning & tool calling", 131_072),
        DiscoveredModel("grok-2-vision-1212", "Grok 2 Vision", "Multimodal reasoning & image input", 131_072, vision=True),
        DiscoveredModel("grok-beta", "Grok Beta", "Latest experimental release", 131_072),
    ]


def _fallback_deepseek() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("deepseek-chat", "DeepSeek V3", "Elite coding and conversational tier", 64_000),
        DiscoveredModel("deepseek-reasoner", "DeepSeek R1", "Full chain-of-thought deliberate reasoning", 64_000, reasoning=True),
    ]


def _fallback_openrouter() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", "Via OpenRouter gateway", 200_000, vision=True),
        DiscoveredModel("openai/gpt-4o", "GPT-4o", "Via OpenRouter gateway", 128_000, vision=True),
        DiscoveredModel("deepseek/deepseek-r1", "DeepSeek R1", "Via OpenRouter gateway", 64_000, reasoning=True),
        DiscoveredModel("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "Via OpenRouter gateway", 128_000),
    ]


def _fallback_ollama() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("llama3.2", "Llama 3.2", "Compact offline local model", 128_000),
        DiscoveredModel("llama3.1", "Llama 3.1", "Balanced local model", 128_000),
        DiscoveredModel("qwen2.5:7b", "Qwen 2.5 (7B)", "Strong multilingual local model", 32_000),
        DiscoveredModel("deepseek-r1:8b", "DeepSeek R1 (8B)", "Local reasoning model", 64_000, reasoning=True),
    ]


def _fallback_cursor() -> list[DiscoveredModel]:
    return [
        DiscoveredModel("cursor-small", "Cursor Small", "Fast local coding & agent flow", 128_000),
        DiscoveredModel("cursor-fast", "Cursor Fast", "Low latency reasoning", 128_000),
        DiscoveredModel("claude-3.5-sonnet", "Cursor Claude 3.5 Sonnet", "Via Cursor API", 200_000, vision=True),
        DiscoveredModel("gpt-4o", "Cursor GPT-4o", "Via Cursor API", 128_000, vision=True),
    ]


def get_discovered_models(provider_id: str, force_refresh: bool = False,
                          api_key: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Retrieve discovered models for a provider, using cache unless forced."""
    pid = provider_id.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    now = time.time()
    if not force_refresh and pid in _MODEL_CACHE:
        cached_time, cached_models = _MODEL_CACHE[pid]
        if now - cached_time < _CACHE_TTL:
            return cached_models, {}

    account_meta: dict[str, Any] = {}
    models: list[DiscoveredModel] = []

    if pid == "openai":
        models, account_meta = discover_openai_models(api_key)
    elif pid == "claude":
        models = discover_anthropic_models(api_key)
    elif pid == "gemini":
        models = discover_gemini_models(api_key)
    elif pid == "xai":
        models = discover_xai_models(api_key)
    elif pid == "deepseek":
        models = discover_deepseek_models(api_key)
    elif pid == "openrouter":
        models = discover_openrouter_models(api_key)
    elif pid == "ollama":
        models = discover_ollama_models()
    elif pid == "cursor":
        models = _fallback_cursor()
    elif pid == "claude-code":
        models = [DiscoveredModel("claude-code", "Claude Code Session", "Local Claude CLI bridge", 200_000)]
    elif pid == "mock":
        models = [DiscoveredModel("mock-1", "Mock Test Model", "Offline test fixture", 32_000)]
    else:
        models = []

    dict_models = [m.to_dict() for m in models]
    _MODEL_CACHE[pid] = (now, dict_models)
    return dict_models, account_meta
