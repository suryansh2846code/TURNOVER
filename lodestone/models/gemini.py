"""Google Gemini provider via official OpenAI-compatible endpoint.

Google provides an official OpenAI-compatible chat completions endpoint for Gemini:
https://generativelanguage.googleapis.com/v1beta/openai/

Supports tool/function calling, system messages, and usage reporting.
Works with gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash.
"""
from __future__ import annotations

import os

from .base import _saved_key
from .openai_compat import OpenAICompatProvider


class GeminiProvider(OpenAICompatProvider):
    name = "gemini"
    default_base = "https://generativelanguage.googleapis.com/v1beta/openai"
    default_model = "gemini-2.5-flash"
    key_env = "GEMINI_API_KEY"
    key_required = True

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        # Check both GEMINI_API_KEY and GOOGLE_API_KEY
        if api_key is not None:
            resolved_key = api_key
        else:
            resolved_key = (
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
                or _saved_key("GEMINI_API_KEY")
                or _saved_key("GOOGLE_API_KEY")
                or ""
            )
        super().__init__(model=model, api_key=resolved_key, base_url=base_url)

    def is_ready(self) -> tuple[bool, str]:
        if self.api_key:
            return True, ""
        try:
            from ..connectors.google_auth import _token_path
            if _token_path().exists():
                return True, ""
        except Exception:
            pass
        return False, "set GEMINI_API_KEY or Sign in with Google"

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        # If no explicit API key is provided, attempt to use the Google OAuth access token
        if not self.api_key:
            try:
                from ..connectors.google_auth import get_credentials
                creds = get_credentials(interactive=False)
                if creds and creds.token:
                    self.api_key = creds.token
            except Exception:
                pass
        return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)

