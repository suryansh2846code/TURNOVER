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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        description="Cursor agent models via Cursor account, CLI, or API key.",
        api_key_supported=True,
        oauth_supported=True,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=True,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=False,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://cursor.com",
        documentation_url="https://docs.cursor.com",
    ),
    "gemini": ProviderCapabilities(
        provider_id="gemini",
        display_name="Google Gemini",
        description="Google Gemini models with multimodal reasoning and long-context capabilities.",
        api_key_supported=True,
        oauth_supported=True,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=True,
        model_discovery_supported=True,
        refresh_supported=True,
        disconnect_supported=True,
        official_auth_url="https://aistudio.google.com/apikey",
        documentation_url="https://ai.google.dev/gemini-api/docs",
    ),
    "xai": ProviderCapabilities(
        provider_id="xai",
        display_name="xAI (Grok)",
        description="xAI's Grok reasoning and conversation models via Grok account or API key.",
        api_key_supported=True,
        oauth_supported=False,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=False,
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
        description="Unified gateway to hundreds of AI models via API key or OAuth PKCE.",
        api_key_supported=True,
        oauth_supported=True,
        browser_login_supported=True,
        device_login_supported=False,
        local_cli_auth_supported=False,
        enterprise_sso_supported=False,
        account_identity_supported=True,
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
