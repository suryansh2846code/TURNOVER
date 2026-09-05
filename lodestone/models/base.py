"""Provider-agnostic LLM interface with tool calling.

Every backend (Claude, OpenAI, OpenRouter, Ollama, or a subscription-session
proxy) implements `LLMProvider.chat`, normalizing its wire format to the same
Message / ToolCall shapes so the agent runtime is model-agnostic — this is the
"bring your own model" layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def _saved_key(env_key: str) -> str:
    """Fall back to a key saved from the UI (~/Library/Lodestone/secrets.json)
    when the matching env var isn't set — so users can paste an API key in the
    onboarding / workspace instead of editing their shell profile."""
    try:
        from ..config import get_settings
        return get_settings().get_secret(env_key) or ""
    except Exception:
        return ""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str                      # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # for role=="tool": which call this answers
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": [tc.__dict__ for tc in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "name": self.name,
        }


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]     # JSON Schema
    handler: Callable[..., str] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ChatResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    finish_reason: str = "stop"
    input_tokens: int = 0        # prompt tokens (0 if the provider doesn't report)
    output_tokens: int = 0       # completion tokens

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider:
    name: str = "base"
    model: str = ""

    def is_ready(self) -> tuple[bool, str]:
        return True, ""

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> ChatResult:  # pragma: no cover - interface
        raise NotImplementedError
