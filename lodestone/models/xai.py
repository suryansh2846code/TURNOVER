"""xAI Grok provider via official OpenAI-compatible endpoint.

xAI exposes an OpenAI-compatible API at https://api.x.ai/v1 with full tool
calling and system prompt support.
Works with grok-2-latest, grok-2-mini, grok-beta, grok-vision-beta.
"""
from __future__ import annotations

import os

from .base import _saved_key
from .openai_compat import OpenAICompatProvider


class XAIProvider(OpenAICompatProvider):
    name = "xai"
    default_base = "https://api.x.ai/v1"
    default_model = "grok-2-1212"
    key_env = "XAI_API_KEY"
    key_required = True

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        if api_key is not None:
            resolved_key = api_key
        else:
            resolved_key = (
                os.environ.get("XAI_API_KEY")
                or _saved_key("XAI_API_KEY")
                or ""
            )
        super().__init__(model=model, api_key=resolved_key, base_url=base_url)

    def is_ready(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "set XAI_API_KEY"
        return True, ""
