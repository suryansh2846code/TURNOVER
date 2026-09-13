"""Provider-Reported & Dynamic Model Entitlement Engine for TURNOVER / Lodestone.

Determines model accessibility dynamically based on:
1. Provider Live Discovery & Capability Reporting (authoritative source of truth).
2. Verified Account Access & Scopes (runtime identity, session validity, and actual API capabilities).
3. Provider-Reported Constraints (e.g. CLI update prerequisites reported by installed tools).
4. Conservative Static Fallback Mappings (safe fallback tier metadata when provider APIs do not expose real-time entitlement endpoints).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..log import suppressed


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
CLAUDE_TIER_MAX = PlanTier("Max", 25)
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
        if "plus" in p or "go" in p:
            return OPENAI_TIER_PLUS
        if "api" in p or "developer" in p:
            return OPENAI_TIER_API
        if "free" in p:
            return OPENAI_TIER_FREE
        return OPENAI_TIER_FREE if plan_str else TIER_ANONYMOUS

    if pid in ("claude", "anthropic", "claude-code"):
        if any(k in p for k in ("enterprise", "api")):
            return CLAUDE_TIER_ENTERPRISE
        if "team" in p:
            return CLAUDE_TIER_TEAM
        if "max" in p:
            return CLAUDE_TIER_MAX
        if any(k in p for k in ("pro", "subscription")):
            return CLAUDE_TIER_PRO
        if "free" in p:
            return CLAUDE_TIER_FREE
        return CLAUDE_TIER_FREE if plan_str else TIER_ANONYMOUS

    if pid == "cursor":
        if any(k in p for k in ("business", "enterprise")):
            return CURSOR_TIER_BUSINESS
        if "pro" in p:
            return CURSOR_TIER_PRO
        if "free" in p:
            return CURSOR_TIER_FREE
        return CURSOR_TIER_FREE if plan_str else TIER_ANONYMOUS

    if pid in ("gemini", "google"):
        if any(k in p for k in ("api", "ai studio", "developer", "vertex")):
            return GEMINI_TIER_API
        if p:
            return GEMINI_TIER_FREE
        return TIER_ANONYMOUS

    if pid in ("xai", "grok"):
        if any(k in p for k in ("tier 2", "supergrok", "tier2", "pro")):
            return XAI_TIER_2
        if p:
            return XAI_TIER_1
        return TIER_ANONYMOUS

    return PlanTier(plan_str or "Standard", 10) if plan_str else TIER_ANONYMOUS


# Required tier per model
_MODEL_TIER_REQUIREMENTS: dict[str, dict[str, PlanTier]] = {
    "openai": {
        "gpt-5.5": OPENAI_TIER_FREE,
        "gpt-5.4": OPENAI_TIER_FREE,
        "gpt-5.4-mini": OPENAI_TIER_FREE,
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
        "claude-haiku-4-5": CLAUDE_TIER_FREE,
        "claude-opus-5": CLAUDE_TIER_PRO,
        "claude-sonnet-5": CLAUDE_TIER_PRO,
        # Fable is a subscription model, not an org-plan one — the "Team /
        # Enterprise" gate previously here came from misreading the CLI's
        # `cc-update-required-1` entry, which is a CLI *version* requirement.
        "claude-fable-5": CLAUDE_TIER_PRO,
    },
    "claude-code": {
        "claude-code": CLAUDE_TIER_FREE,
        "claude-haiku-4-5": CLAUDE_TIER_FREE,
        "claude-opus-5": CLAUDE_TIER_PRO,
        "claude-sonnet-5": CLAUDE_TIER_PRO,
        "claude-fable-5": CLAUDE_TIER_PRO,
    },
    "cursor": {
        # A free Cursor plan can run ONLY `auto`; every named model is refused
        # by the CLI ("Named models unavailable").
        "auto": CURSOR_TIER_FREE,
    },
    "gemini": {
        "gemini-3.7-flash": GEMINI_TIER_FREE,
        "gemini-3.6-flash": GEMINI_TIER_FREE,
        "gemini-2.5-flash": GEMINI_TIER_FREE,
        "gemini-3.1-pro-preview": GEMINI_TIER_API,
        "gemini-2.5-pro": GEMINI_TIER_API,
    },
    "xai": {
        "grok-4.3": XAI_TIER_1,
        "grok-4.5": XAI_TIER_1,
        "grok-4.6": XAI_TIER_2,
    },
    "subscription": {
        "gpt-5.6-terra": PlanTier("Standard", 10),
        "claude-opus-5": PlanTier("Standard", 10),
        "claude-sonnet-5": PlanTier("Standard", 10),
        "claude-fable-5": PlanTier("Standard", 10),
    },
}


# Some providers gate by exception rather than by list: Cursor's free plan runs
# ONLY `auto`, so anything not named above needs Pro. Without this an unlisted
# model falls through to "no restriction" and is offered, then refused by the
# CLI.
_PROVIDER_DEFAULT_TIER: dict[str, PlanTier] = {
    "cursor": CURSOR_TIER_PRO,
}


def evaluate_model_entitlement(
    provider: str,
    model_id: str,
    is_connected: bool,
    user_plan: str | None = None,
    context: dict[str, Any] | None = None,
    provider_reported: tuple[bool, str | None] | None = None,
) -> tuple[bool, str | None]:
    """Decide whether THIS user, on THEIR plan, can run this model.

    Authority runs strictly in this order — the first answer wins:

      1. **Connection.** Nothing is usable until the user connects the provider.
      2. **The provider's own answer** (`provider_reported`): what the account
         itself says it can run — a live ``/v1/models`` query made with the
         user's credential, the Codex models cache, the Claude CLI's model
         options, the locally installed Ollama tags. This is the truth and it
         is never second-guessed by the tables below.
      3. **Static tier tables.** A conservative guess used ONLY when step 2 has
         nothing to say: the user is not connected yet, or discovery failed and
         a hardcoded fallback list is being shown.

    Passing `provider_reported` is what makes availability match the user's real
    plan on any machine, rather than whatever list was hardcoded at build time.

    Returns (locked, plan_required); `plan_required` explains a lock.
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

    # Gate 4: the account's own answer. A model the provider handed us for this
    # user's credential is available to this user, whatever our tables guess.
    if provider_reported is not None:
        reported_locked, reported_plan = provider_reported
        if reported_locked:
            return True, reported_plan or "Not available on your plan"
        return False, None

    # Gate 5: static tier requirements — a fallback for models we are listing
    # without having asked the provider (not connected, or discovery failed).
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
        req_tier = _PROVIDER_DEFAULT_TIER.get(pid)
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
        "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
        "gpt-6-astra", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna",
        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro-preview",
        "gemini-2.5-flash", "gemini-2.5-pro",
        "auto",
        "grok-4.6", "grok-4.5", "grok-4.3",
        "deepseek-chat", "deepseek-reasoner",
        "llama3.2", "qwen2.5",
    ]

    for pref in priority_order:
        for m in unlocked:
            if pref in m.lower():
                return m

    return unlocked[0]


# Providers that hold an account credential *and* an API key independently.
_DUAL_CREDENTIAL_PROVIDERS = {"openai", "claude", "cursor"}

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "cursor": "CURSOR_API_KEY",
    "xai": "XAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _stored_api_key(pid: str, api_key: str | None = None) -> str:
    """The API key for this provider, ignoring one the user has disconnected."""
    import os

    from .base import _saved_key
    from .connections import ConnectionStatus, get_connection

    if api_key:
        return api_key
    env = _PROVIDER_KEY_ENV.get(pid)
    if not env:
        return ""
    if get_connection(pid).api_key_status == ConnectionStatus.DISCONNECTED:
        return ""
    return os.environ.get(env) or _saved_key(env) or ""


def _detect_account(pid: str) -> dict[str, Any]:
    """Live account-credential state, independent of any API key."""
    from .connections import ConnectionStatus, get_connection

    conn = get_connection(pid)
    if conn.account_status == ConnectionStatus.DISCONNECTED:
        return {}

    if pid in ("claude", "claude-code"):
        # Finding a CLI or a config file on the machine is *detection*, not
        # consent. The user must connect the provider before we will use it.
        if not conn.account_connected:
            return {}
        from .accounts import detect_claude_account
        acct = detect_claude_account()
        if pid == "claude-code":
            from .claude_code import find_claude
            return acct if find_claude() else {}
        return acct

    if pid == "cursor":
        from .accounts import detect_cursor_account
        return detect_cursor_account() if conn.account_connected else {}

    if pid == "openai":
        from .chatgpt_auth import detect_chatgpt_local_session
        session = detect_chatgpt_local_session(fetch_usage=False)
        if session and (conn.account_connected or session.get("has_token")):
            return session
        return {}

    if pid == "xai":
        # An OAuth token is deliberately NOT an account credential here: it
        # authenticates at api.x.ai and is then refused for billing. The
        # subscription runs through xAI's CLI instead.
        from .grok_cli import find_grok_cli, grok_cli_auth_status

        # The binary being on disk is detection, and detection is not an
        # account: an installed-but-signed-out CLI was reported here as a Grok
        # subscription, which put a "Connected" badge on a provider that could
        # not answer a single message.
        if find_grok_cli() and grok_cli_auth_status().get("authenticated"):
            return {"email": conn.email or "Grok CLI", "plan": "Grok subscription"}
        return {}

    return {}


def provider_credentials(provider_id: str, api_key: str | None = None) -> dict[str, dict[str, Any]]:
    """Report each credential a provider holds, independently.

    An account and an API key are separate things: removing one must never
    disconnect the other, and connecting one must never claim the other is
    connected. Everything downstream reads this, not a single shared status.
    """
    pid = provider_id.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    from .capabilities import get_capabilities

    caps = get_capabilities(pid)
    # A key-only provider has no account credential by definition. xAI is the
    # case that matters: an OAuth token authenticates but grants no api.x.ai
    # credits, so counting it as "connected" would unlock models that fail on
    # the first message.
    account_supported = bool(caps and not caps.api_key_only) and (
        pid in _DUAL_CREDENTIAL_PROVIDERS or pid in ("claude-code", "xai"))

    key = _stored_api_key(pid, api_key)
    account = _detect_account(pid) if account_supported else {}

    return {
        "api_key": {
            "connected": bool(key),
            "reference": _PROVIDER_KEY_ENV.get(pid, ""),
            "supported": bool(_PROVIDER_KEY_ENV.get(pid)),
        },
        "account": {
            "connected": bool(account),
            "email": account.get("email"),
            "plan": account.get("plan"),
            "supported": account_supported,
            "meta": account,
        },
    }


def is_provider_connected(provider_id: str, api_key: str | None = None) -> tuple[bool, str | None, dict[str, Any]]:
    """Whether a provider can run inference at all, plus plan and metadata.

    Connected if **either** credential works. The API key wins for plan
    reporting when both are present, matching how inference picks a path.
    """
    import os

    from .connections import ConnectionStatus, get_connection

    pid = provider_id.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    conn = get_connection(pid)

    # ── providers with no per-credential split ───────────────────────────
    if pid == "mock":
        return True, "Mock", {}

    if pid == "ollama":
        import httpx
        url = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        with suppressed("if httpx.get(f'{url.rstrip('/')}/api/tags', timeout=1.5).status_ …"):
            if httpx.get(f"{url.rstrip('/')}/api/tags", timeout=1.5).status_code == 200:
                return True, "Ollama Local", {"host": url}
        return False, None, {}

    if pid == "subscription":
        # Only "connected" once a gateway is actually configured — otherwise the
        # catalog advertises models that every request would fail on.
        base = os.environ.get("LODESTONE_SUBSCRIPTION_BASE_URL")
        if not base or conn.connection_status == ConnectionStatus.DISCONNECTED:
            return False, None, {}
        return True, "Subscription Gateway", {"host": base}

    if pid == "gemini":
        if conn.api_key_status == ConnectionStatus.DISCONNECTED:
            return False, None, {}
        from .gemini import resolve_gemini_credentials
        cred = resolve_gemini_credentials(api_key=api_key)
        if cred.valid:
            return True, "Google AI Studio", {
                "email": cred.email or conn.email or "API Key User",
                "source": "api_key",
                "has_api_key": True,
            }
        return False, None, {
            "source": "none",
            "error_reason": cred.error_reason,
            "has_api_key": False,
        }

    # ── the rest: either credential is enough ────────────────────────────
    creds = provider_credentials(pid, api_key)
    key_cred, account_cred = creds["api_key"], creds["account"]

    if key_cred["connected"]:
        plans = {
            "openai": "OpenAI Developer", "claude": "Anthropic API",
            "cursor": "Cursor API", "xai": "xAI Grok",
            "deepseek": "DeepSeek Account", "openrouter": "OpenRouter Account",
        }
        return True, plans.get(pid, "API Key"), {"email": conn.email or "Developer"}

    if account_cred["connected"]:
        meta = account_cred["meta"]
        plan = account_cred["plan"] or {
            "openai": "ChatGPT Account", "claude": "Claude Subscription",
            "cursor": "Cursor", "claude-code": "Claude CLI",
        }.get(pid)
        return True, plan, {**meta, "email": account_cred["email"] or conn.email}

    return False, None, {}


# Backends that accept any model string, so absence from a catalog means nothing.
_ACCEPTS_ANY_MODEL = {"mock"}


def _best_for_account(provider_id: str) -> str | None:
    """The strongest model this account is actually offered, or None.

    None is still the right answer when we cannot tell — a discovery failure or
    a hardcoded fallback list is not evidence about this account, and guessing
    from one would override a model the user can legitimately run.
    """
    try:
        from .discovery import get_discovered_models
        offered, _ = get_discovered_models(provider_id)
    except Exception:
        return None
    if not offered or any(m.get("is_fallback") for m in offered):
        return None
    unlocked = [m["id"] for m in offered if not m.get("locked")]
    if not unlocked:
        return None
    return get_best_unlocked_model(
        provider=provider_id, available_models=unlocked,
        is_connected=True, user_plan=None) or unlocked[0]


def resolve_usable_model(provider_id: str, model: str | None) -> tuple[str | None, str | None]:
    """Map a *requested* model onto one this user can actually run right now.

    A model id is chosen once and then persisted — in an agent's binding, in
    localStorage — but the provider's catalog moves underneath it. Sending a
    retired or plan-locked id straight through produces a provider 400 on the
    user's next message, so every request is re-checked against what the
    account currently offers.

    Returns (usable_model, replaced) where `replaced` is the original id when a
    substitution happened, else None. A `None` model means "let the provider
    pick its own default".
    """
    if provider_id.lower() in _ACCEPTS_ANY_MODEL:
        return (model or None), None

    if not model:
        # "Auto" has to mean "the best model this account can actually run",
        # not "whatever id is hardcoded as the provider's default". Returning
        # None here deferred to `registry.default_model`, which for OpenAI is
        # `gpt-5.6-terra` — a model a ChatGPT Free account cannot run. The user
        # then got "requires Pro" about a model they never chose, from the one
        # setting that is supposed to be the safe choice.
        return _best_for_account(provider_id), None

    try:
        from .discovery import get_discovered_models
        offered, _ = get_discovered_models(provider_id)
    except Exception:
        # Never block a turn on a discovery failure — honour what was asked.
        return model, None

    if not offered:
        return model, None

    by_id = {m["id"]: m for m in offered}
    match = by_id.get(model)
    if match is not None and not match.get("locked"):
        return model, None

    if match is None and any(m.get("is_fallback") for m in offered):
        # We are showing a hardcoded list, not the account's real catalog, so an
        # id being absent from it proves nothing. Substituting here would swap a
        # model the user can legitimately run.
        return model, None

    # Only ever choose among models discovery already marked unlocked. That
    # flag was computed against what this account reports it can run
    # (`discovery.py`: `locked = not is_supported`), and it is the only place
    # the user's plan is actually known.
    #
    # This used to hand `get_best_unlocked_model` the *whole* list with
    # `user_plan=None`, which re-derived entitlement with no plan to check
    # against — so every model looked unlocked and the repair returned the
    # highest-priority one. For a ChatGPT Free account that is `gpt-5.6-terra`:
    # the function whose entire job is to replace a plan-locked model handed
    # back a plan-locked model, and the user got "requires Pro" on a model they
    # never chose.
    unlocked = [m["id"] for m in offered if not m.get("locked")]
    substitute = get_best_unlocked_model(
        provider=provider_id,
        available_models=unlocked,
        is_connected=True,
        user_plan=None,
    ) or (unlocked[0] if unlocked else None)

    if substitute and substitute != model:
        return substitute, model
    if substitute:
        return substitute, None
    # Nothing is usable — fall back to the provider's own default rather than
    # sending an id we know the provider will reject.
    return None, model
