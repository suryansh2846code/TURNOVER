"""Anthropic (Claude) provider via the Messages API."""
from __future__ import annotations

import json
import os
import uuid

import httpx

from .base import ChatResult, LLMProvider, Message, Tool, ToolCall, _saved_key


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-3-7-sonnet-latest")
        self.api_key = api_key if api_key is not None else (os.environ.get("ANTHROPIC_API_KEY", "") or _saved_key("ANTHROPIC_API_KEY"))
        self.base_url = os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )

    def is_ready(self) -> tuple[bool, str]:
        if self.api_key:
            return True, ""
        try:
            from .connections import ConnectionStatus, get_connection
            conn = get_connection("claude")
            if conn.connection_status == ConnectionStatus.DISCONNECTED:
                return False, "Disconnected. Set ANTHROPIC_API_KEY or sign in with Claude"
            if conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED:
                return True, ""
            from .claude_code import find_claude
            if find_claude():
                return True, ""
        except Exception:
            pass
        return False, "set ANTHROPIC_API_KEY or connect Claude account"

    def _to_blocks(self, messages: list[Message]) -> tuple[str, list[dict]]:
        system = ""
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                system = (system + "\n" + m.content).strip()
            elif m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append({
                        "type": "tool_use", "id": tc.id,
                        "name": tc.name, "input": tc.arguments,
                    })
                out.append({"role": "assistant", "content": blocks or m.content})
            elif m.role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                }]})
        return system, out

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        system, msgs = self._to_blocks(messages)
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": msgs,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [{
                "name": t.name, "description": t.description,
                "input_schema": t.parameters,
            } for t in tools]

        resp = httpx.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        text_parts, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(
                    id=block.get("id", str(uuid.uuid4())),
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))
        usage = data.get("usage") or {}
        return ChatResult(
            text="".join(text_parts),
            tool_calls=calls,
            raw=data,
            finish_reason=data.get("stop_reason", "stop"),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )
