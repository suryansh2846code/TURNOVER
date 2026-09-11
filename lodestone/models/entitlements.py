"""Universal Provider Plan & Model Entitlement Engine for TURNOVER / Lodestone.

Determines model accessibility dynamically based on:
1. Provider Connection State:
   - If a provider is not connected (no API key, unauthenticated session, offline daemon),
     all models are gated with `locked = True` and `plan_required = "Connect in Models"`.
2. Provider Plan Tier:
   - Once connected, models are evaluated against the authenticated user's tier.
   - Models are unlocked (`locked = False`) if the user's tier meets or exceeds the requirement.
   - Higher-tier models are locked with clear plan badges (e.g. `🔒 Pro`, `🔒 Plus`, `🔒 Pull required`).
3. Explicit Provider Constraints:
   - Honors explicit disablement flags (e.g., CLI version prerequisites from `~/.claude.json`).

Completely zero-hardcoded: works identically for ANY user, ANY account ID/email, on any OS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanTier:
    name: str
    level: int  # Higher number = higher capability / privileges


# Standard tier levels for providers
TIER_ANONYMOUS = PlanTier("Anonymous", 0)

# OpenAI / ChatGPT tiers
OPENAI_TIER_FREE = PlanTier("Free", 10)
OPENAI_TIER_PLUS = PlanTier("Plus", 20)
OPENAI_TIER_PRO = PlanTier("Pro", 30)
OPENAI_TIER_API = PlanTier("API Key", 40)

# Claude / Anthropic tiers
CLAUDE_TIER_FREE = PlanTier("Free", 10)
CLAUDE_TIER_PRO = PlanTier("Pro", 20)
CLAUDE_TIER_TEAM = PlanTier("Team", 30)
CLAUDE_TIER_ENTERPRISE = PlanTier("Enterprise", 40)

# Cursor tiers
CURSOR_TIER_FREE = PlanTier("Free", 10)
CURSOR_TIER_PRO = PlanTier("Pro", 20)
CURSOR_TIER_BUSINESS = PlanTier("Business", 30)

# Google Gemini tiers
GEMINI_TIER_FREE = PlanTier("Free", 10)
GEMINI_TIER_API = PlanTier("API Key / AI Studio", 20)

# xAI tiers
XAI_TIER_1 = PlanTier("Tier 1", 10)
XAI_TIER_2 = PlanTier("SuperGrok / Tier 2", 20)


def normalize_plan_tier(provider: str, plan_str: str | None) -> PlanTier:
    """Map any raw plan string or organizationType into a normalized PlanTier."""
    p = (plan_str or "").strip().lower()
    pid = provider.lower()

    if pid in ("openai", "chatgpt"):
        if any(k in p for k in ("pro", "team", "business", "enterprise", "edu", "self_serve")):
            return OPENAI_TIER_PRO
        elif "plus" in p or "go" in p:
            return OPENAI_TIER_PLUS
        elif "api" in p or "developer" in p:
            return OPENAI_TIER_API
        elif "free" in p:
            return OPENAI_TIER_FREE
        return OPENAI_TIER_FREE if plan_str else TIER_ANONYMOUS

    elif pid in ("claude", "anthropic", "claude-code"):
        if any(k in p for k in ("enterprise", "api")):
            return CLAUDE_TIER_ENTERPRISE
        elif "team" in p:
            return CLAUDE_TIER_TEAM
        elif any(k in p for k in ("pro", "subscription")):
            return CLAUDE_TIER_PRO
        elif "free" in p:
            return CLAUDE_TIER_FREE
        return CLAUDE_TIER_FREE if plan_str else TIER_ANONYMOUS

    elif pid == "cursor":
        if any(k in p for k in ("business", "enterprise")):
            return CURSOR_TIER_BUSINESS
        elif "pro" in p:
            return CURSOR_TIER_PRO
        elif "free" in p:
            return CURSOR_TIER_FREE
        return CURSOR_TIER_FREE if plan_str else TIER_ANONYMOUS

    elif pid in ("gemini", "google"):
        if any(k in p for k in ("api", "ai studio", "developer", "vertex")):
            return GEMINI_TIER_API
        elif p:
            return GEMINI_TIER_FREE
        return TIER_ANONYMOUS

    elif pid in ("xai", "grok"):
        if any(k in p for k in ("tier 2", "supergrok", "tier2", "pro")):
            return XAI_TIER_2
        elif p:
            return XAI_TIER_1
        return TIER_ANONYMOUS

    return PlanTier(plan_str or "Standard", 10) if plan_str else TIER_ANONYMOUS


# Required tier per model
_MODEL_TIER_REQUIREMENTS: dict[str, dict[str, PlanTier]] = {
    "openai": {
        "gpt-5.5": OPENAI_TIER_FREE,
        "gpt-5.6-terra": OPENAI_TIER_FREE,
        "gpt-5.6-luna": OPENAI_TIER_FREE,
        "gpt-reserve": OPENAI_TIER_FREE,
        "codex-auto-review": OPENAI_TIER_FREE,
        "o3-mini": OPENAI_TIER_PLUS,
        "o1-mini": OPENAI_TIER_PLUS,
        "gpt-6-astra": OPENAI_TIER_PRO,
        "gpt-5.6-sol": OPENAI_TIER_PRO,
        "o1": OPENAI_TIER_PRO,
        "o3": OPENAI_TIER_PRO,
    },
    "claude": {
        "claude-3-5-haiku-latest": CLAUDE_TIER_FREE,
        "claude-3-5-haiku": CLAUDE_TIER_FREE,
        "claude-3-5-sonnet-latest": CLAUDE_TIER_FREE,
        "claude-3-5-sonnet": CLAUDE_TIER_FREE,
        "claude-3-7-sonnet-latest": CLAUDE_TIER_FREE,
        "claude-3-7-sonnet": CLAUDE_TIER_FREE,
        "claude-opus-5": CLAUDE_TIER_PRO,
        "claude-sonnet-5": CLAUDE_TIER_PRO,
        "claude-fable-5-1": CLAUDE_TIER_TEAM,
        "claude-fable-5": CLAUDE_TIER_TEAM,
    },
    "claude-code": {
        "claude-code": CLAUDE_TIER_FREE,
        "claude-3-5-sonnet": CLAUDE_TIER_FREE,
        "claude-3-7-sonnet": CLAUDE_TIER_FREE,
        "claude-opus-5": CLAUDE_TIER_PRO,
        "claude-sonnet-5": CLAUDE_TIER_PRO,
        "claude-fable-5-1": CLAUDE_TIER_TEAM,
    },
    "cursor": {
        "cursor-fast": CURSOR_TIER_FREE,
        "cursor-small": CURSOR_TIER_FREE,
        "claude-opus-5": CURSOR_TIER_PRO,
        "claude-3.7-sonnet": CURSOR_TIER_PRO,
        "gpt-5.6-terra": CURSOR_TIER_PRO,
    },
    "gemini": {
        "gemini-2.0-flash": GEMINI_TIER_FREE,
        "gemini-2.5-flash": GEMINI_TIER_FREE,
        "gemini-2.5-pro": GEMINI_TIER_API,
    },
    "xai": {
        "grok-2-1212": XAI_TIER_1,
        "grok-2-latest": XAI_TIER_1,
        "grok-2-vision-latest": XAI_TIER_1,
        "grok-3-mini": XAI_TIER_1,
        "grok-3": XAI_TIER_2,
    },
    "subscription": {
        "gpt-5.6-terra": PlanTier("Standard", 10),
        "claude-opus-5": PlanTier("Standard", 10),
        "claude-sonnet-5": PlanTier("Standard", 10),
        "claude-3-7-sonnet": PlanTier("Standard", 10),
        "claude-fable-5-1": PlanTier("Enterprise", 30),
    },
}


def evaluate_model_entitlement(
    provider: str,
    model_id: str,
    is_connected: bool,
    user_plan: str | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Evaluate whether a model is unlocked for the user.

    Returns:
        (locked: bool, plan_required: str | None)
        - locked=False: Model is unlocked and immediately usable.
        - locked=True: Model is locked; plan_required explains what is needed.
    """
    pid = provider.lower()
    mid = model_id.lower()
    ctx = context or {}

    # Gate 1: Provider must be connected in the Models section
    if not is_connected:
        return True, "Connect in Models"

    # Gate 2: Ollama installed model check
    if pid == "ollama":
        installed_names = {str(x).lower() for x in (ctx.get("installed_models") or set())}
        base = mid.split(":")[0]
        is_installed = (
            mid in installed_names
            or base in installed_names
            or any(inst.split(":")[0] == base for inst in installed_names)
        )
        if not is_installed:
            return True, "Pull required"
        return False, None

    # Gate 3: Explicit session disablement flags (e.g. CLI update requirement in ~/.claude.json)
    disabled_models = ctx.get("disabled_models") or {}
    for d_pattern, reason in disabled_models.items():
        if d_pattern.lower() in mid:
            return True, reason or "Update Required"

    # Gate 4: Provider Tier Requirements
    prov_reqs = _MODEL_TIER_REQUIREMENTS.get(pid, {})
    # Exact match or normalized slug match
    req_tier = prov_reqs.get(model_id) or prov_reqs.get(mid)
    if not req_tier:
        # Check substring match
        for m_key, tier in prov_reqs.items():
            if m_key in mid:
                req_tier = tier
                break

    if not req_tier:
        # Model has no special tier restriction -> available once connected
        return False, None

    user_tier = normalize_plan_tier(pid, user_plan)

    if user_tier.level >= req_tier.level:
        return False, None

    return True, req_tier.name


def get_best_unlocked_model(
    provider: str,
    available_models: list[str],
    is_connected: bool,
    user_plan: str | None = None,
    context: dict[str, Any] | None = None,
) -> str | None:
    """Find the highest-priority model that is currently unlocked for the user."""
    if not is_connected or not available_models:
        return None

    pid = provider.lower()
    unlocked = [
        m for m in available_models
        if not evaluate_model_entitlement(pid, m, is_connected, user_plan, context)[0]
    ]
    if not unlocked:
        return None

    # Priority preferences when choosing automatic default
    priority_order = [
        "claude-opus-5", "claude-sonnet-5", "claude-3-7-sonnet",
        "gpt-6-astra", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna",
        "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
        "cursor-fast", "cursor-small",
        "grok-3", "grok-3-mini",
        "deepseek-chat", "deepseek-reasoner",
        "llama3.2", "qwen2.5",
    ]

    for pref in priority_order:
        for m in unlocked:
            if pref in m.lower():
                return m

    return unlocked[0]


def is_provider_connected(provider_id: str, api_key: str | None = None) -> tuple[bool, str | None, dict[str, Any]]:
    """Determine whether a provider is connected, and retrieve user plan and metadata.

    Returns:
        (is_connected: bool, user_plan: str | None, account_info: dict[str, Any])
    """
    import os
    from .base import _saved_key
    from .connections import ConnectionStatus, get_connection

    pid = provider_id.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    conn = get_connection(pid)
    is_disconnected = (conn.connection_status == ConnectionStatus.DISCONNECTED)

    if pid == "mock":
        return True, "Mock", {}

    if pid == "ollama":
        # Check if Ollama daemon is reachable
        import httpx
        url = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        try:
            r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=1.5)
            if r.status_code == 200:
                return True, "Ollama Local", {"host": url}
        except Exception:
            pass
        return False, None, {}

    if pid == "claude-code":
        from .claude_code import find_claude
        from .accounts import detect_claude_account
        acct = detect_claude_account()
        bin_path = find_claude()
        if not bin_path or is_disconnected:
            return False, None, {}
        plan = acct.get("plan") if acct.get("found_on_computer") else "Claude CLI"
        return True, plan, acct

    if pid == "openrouter":
        key = api_key or os.environ.get("OPENROUTER_API_KEY") or _saved_key("OPENROUTER_API_KEY")
        if not key or is_disconnected:
            return False, None, {}
        return True, "OpenRouter Account", {"email": conn.email or "OpenRouter User"}

    if pid == "deepseek":
        key = api_key or os.environ.get("DEEPSEEK_API_KEY") or _saved_key("DEEPSEEK_API_KEY")
        if not key or is_disconnected:
            return False, None, {}
        return True, "DeepSeek Account", {"email": conn.email or "DeepSeek User"}

    if pid == "xai":
        key = api_key or os.environ.get("XAI_API_KEY") or _saved_key("XAI_API_KEY")
        if (not key and conn.connection_status not in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED)) or is_disconnected:
            return False, None, {}
        return True, "Grok Account", {"email": conn.email or "xAI Grok"}

    if pid == "gemini":
        from .accounts import detect_google_account
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _saved_key("GEMINI_API_KEY")
        acct = detect_google_account()
        if is_disconnected:
            return False, None, {}
        if key:
            return True, "Google AI Studio", {"email": conn.email or acct.get("email") or "Developer"}
        if acct.get("connected"):
            return True, acct.get("plan", "Google Gemini"), acct
        if conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
            return True, "Google Gemini", {"email": conn.email}
        return False, None, {}

    if pid == "claude":
        from .accounts import detect_claude_account
        key = api_key or os.environ.get("ANTHROPIC_API_KEY") or _saved_key("ANTHROPIC_API_KEY")
        acct = detect_claude_account()
        if is_disconnected:
            return False, None, {}
        if key:
            return True, "Anthropic API", {"email": conn.email or acct.get("email") or "Developer"}
        if acct.get("found_on_computer"):
            return True, acct.get("plan", "Claude Pro"), acct
        if conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
            return True, "Claude Subscription", {"email": conn.email}
        return False, None, {}

    if pid == "cursor":
        from .accounts import detect_cursor_account
        key = api_key or os.environ.get("CURSOR_API_KEY") or _saved_key("CURSOR_API_KEY")
        acct = detect_cursor_account()
        if is_disconnected:
            return False, None, {}
        if key:
            return True, "Cursor API", {"email": conn.email or acct.get("email") or "Developer"}
        if acct.get("found_on_computer"):
            return True, acct.get("plan", "Cursor Free"), acct
        if conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
            return True, "Cursor", {"email": conn.email}
        return False, None, {}

    if pid == "openai":
        from .accounts import detect_openai_account
        key = api_key or os.environ.get("OPENAI_API_KEY") or _saved_key("OPENAI_API_KEY")
        acct = detect_openai_account()
        if is_disconnected:
            return False, None, {}
        if key:
            return True, "OpenAI Developer", {"email": conn.email or acct.get("email") or "Developer"}
        if acct.get("found_on_computer") or acct.get("connected"):
            return True, acct.get("plan", "ChatGPT Free"), acct
        if conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
            return True, "ChatGPT Account", {"email": conn.email}
        return False, None, {}

    if pid == "subscription":
        return True, "Codex Gateway", {}

    return False, None, {}
