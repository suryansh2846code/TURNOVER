"""Provider capability registry for TURNOVER / Lodestone.

Defines real, verified capabilities for each supported AI provider:
- API key authentication
- Official OAuth / browser sign-in (where legitimately supported for 3rd-party API access)
- Local CLI authentication
- Account identity discovery (e.g. email / organization lookup)
- Dynamic model discovery API
- Refresh & disconnect support
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProviderCapabilities:
    provider_id: str
    display_name: str
    description: str
    api_key_supported: bool
    oauth_supported: bool
    browser_login_supported: bool
    device_login_supported: bool
    local_cli_auth_supported: bool
    enterprise_sso_supported: bool
    account_identity_supported: bool
    model_discovery_supported: bool
    refresh_supported: bool
    disconnect_supported: bool
    official_auth_url: str
    documentation_url: str

    @property
    def has_interactive_signin(self) -> bool:
        """Is there a sign-in that ends with a credential we can use?

        A local CLI only counts when the provider actually has an account to
        sign into — Ollama has a CLI but no account, so offering it a sign-in
        button would be a control that does nothing.
        """
        return bool(
            self.oauth_supported or self.browser_login_supported
            or self.device_login_supported
            or (self.local_cli_auth_supported and self.account_identity_supported)
        )

    @property
    def api_key_only(self) -> bool:
        """No interactive sign-in exists for this provider — a key is the only way."""
        return self.api_key_supported and not (
            self.oauth_supported or self.browser_login_supported
            or self.device_login_supported or self.local_cli_auth_supported
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["api_key_only"] = self.api_key_only
        d["has_interactive_signin"] = self.has_interactive_signin
        return d


CAPABILITIES_REGISTRY: dict[str, ProviderCapabilities] = {
    "claude": ProviderCapabilities(
        provider_id="claude",
        display_name="Claude (Anthropic)",
        description="Anthropic's hybrid reasoning and coding models via Claude account, local CLI, or API key.",
        api_key_supported=True,
        oauth_supported=True,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://console.anthropic.com/settings/keys",
        documentation_url="https://docs.anthropic.com/en/api/getting-started",
    ),
    "cursor": ProviderCapabilities(
        provider_id="cursor",
        display_name="Cursor",
        # Cursor exposes no chat-completions API — models run through its
        # headless CLI (`agent -p`), which owns the sign-in. A browser flow
        # here would end without a credential Lodestone can use.
        description="Cursor's models via the Cursor CLI (`agent`), on your own Cursor plan.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=False,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://cursor.com/docs/cli/overview",
        documentation_url="https://cursor.com/docs/cli/headless",
    ),
    "gemini": ProviderCapabilities(
        provider_id="gemini",
        display_name="Google Gemini",
        description="Google Gemini models via Google AI Studio API key.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://aistudio.google.com/apikey",
        documentation_url="https://ai.google.dev/gemini-api/docs",
    ),
    "xai": ProviderCapabilities(
        provider_id="xai",
        display_name="xAI (Grok)",
        # Two paths: a console.x.ai API key, or a SuperGrok subscription via
        # xAI's official Grok CLI (which owns its own sign-in). No browser flow
        # here — an OAuth token authenticates at api.x.ai and is then refused
        # for billing, so offering one would promise what cannot work.
        description="xAI's Grok models via the Grok CLI (your subscription) or a console.x.ai API key.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://console.x.ai",
        documentation_url="https://docs.x.ai",
    ),
    "openai": ProviderCapabilities(
        provider_id="openai",
        display_name="OpenAI",
        description="OpenAI's flagship models via ChatGPT subscription account or API key.",
        api_key_supported=True,
        oauth_supported=True,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://platform.openai.com/api-keys",
        documentation_url="https://platform.openai.com/docs",
    ),
    "deepseek": ProviderCapabilities(
        provider_id="deepseek",
        display_name="DeepSeek",
        description="DeepSeek V3 and R1 reasoning models via official developer API.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://platform.deepseek.com/api_keys",
        documentation_url="https://api-docs.deepseek.com",
    ),
    "openrouter": ProviderCapabilities(
        provider_id="openrouter",
        display_name="OpenRouter",
        # API key only — no OAuth flow is implemented, and advertising one
        # rendered a "Sign in with OpenRouter" button that did nothing.
        description="Unified gateway to hundreds of AI models via an OpenRouter API key.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://openrouter.ai/keys",
        documentation_url="https://openrouter.ai/docs",
    ),
    "ollama": ProviderCapabilities(
        provider_id="ollama",
        display_name="Ollama (Local)",
        description="Local private inference running directly on your Mac. Offline, zero token cost.",
        api_key_supported=False,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=False,
        official_auth_url="",
        documentation_url="https://ollama.com",
    ),
    "claude-code": ProviderCapabilities(
        provider_id="claude-code",
        display_name="Claude Code CLI",
        description="Runs through your existing local Anthropic Claude CLI terminal session.",
        api_key_supported=False,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=False,
        refresh_supported=True,
        disconnect_supported=False,
        official_auth_url="",
        documentation_url="https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
    ),
    "subscription": ProviderCapabilities(
        provider_id="subscription",
        display_name="Subscription Gateway",
        description="Any OpenAI-compatible gateway you run, set via LODESTONE_SUBSCRIPTION_BASE_URL.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=False,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="",
        documentation_url="",
    ),
    "mock": ProviderCapabilities(
        provider_id="mock",
        display_name="Mock (Offline)",
        description="Deterministic offline test provider for unit tests and local development.",
        api_key_supported=False,
        oauth_supported=False,
        browser_login_supported=False,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=False,
        model_discovery_supported=False,
        refresh_supported=False,
        disconnect_supported=False,
        official_auth_url="",
        documentation_url="",
    ),
}


def get_capabilities(provider_id: str) -> ProviderCapabilities | None:
    pid = provider_id.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"
    return CAPABILITIES_REGISTRY.get(pid)


def list_capabilities() -> list[dict[str, Any]]:
    return [c.to_dict() for c in CAPABILITIES_REGISTRY.values()]
