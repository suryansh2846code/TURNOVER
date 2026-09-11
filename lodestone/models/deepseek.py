"""DeepSeek provider via official API.

Connects to https://api.deepseek.com/v1 with tool calling and reasoning support.
Works with deepseek-chat (DeepSeek V3) and deepseek-reasoner (DeepSeek R1).
"""
from __future__ import annotations

import os

from .base import _saved_key
from .openai_compat import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    default_base = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"
    key_env = "DEEPSEEK_API_KEY"
    key_required = True

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        if api_key is not None:
            resolved_key = api_key
        else:
            resolved_key = (
                os.environ.get("DEEPSEEK_API_KEY")
                or _saved_key("DEEPSEEK_API_KEY")
                or ""
            )
        super().__init__(model=model, api_key=resolved_key, base_url=base_url)

    def is_ready(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "set DEEPSEEK_API_KEY"
        return True, ""
