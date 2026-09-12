"""Anthropic (Claude) provider.

Two credentials reach Claude and they are NOT interchangeable:

  • an **API key** -> the Messages API at api.anthropic.com, billed per token.
  • a **subscription** (Claude Pro / Max / Team, connected as an account)
    -> there is no subscription inference endpoint. The only way to run it is
    the local Claude CLI, so those calls are delegated to ClaudeCodeProvider.

Sending a subscription request to the Messages API without a key is a 401, so
the two paths are chosen explicitly rather than falling through.
"""
from __future__ import annotations

import json
import os
import uuid

import httpx

from .base import ChatResult, LLMProvider, Message, ToolCall, _saved_key
from .errors import (ErrorKind, ProviderError, classify_exception,
                     classify_http)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        self.api_key = api_key if api_key is not None else (os.environ.get("ANTHROPIC_API_KEY", "") or _saved_key("ANTHROPIC_API_KEY"))
        self.base_url = os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        self._cli: LLMProvider | None = None

    def is_ready(self) -> tuple[bool, str]:
        if self.api_key:
            return True, ""
        try:
            from .connections import ConnectionStatus, get_connection
            conn = get_connection("claude")
            if conn.account_status == ConnectionStatus.DISCONNECTED:
                return False, "Disconnected. Set ANTHROPIC_API_KEY or sign in with Claude"
            # An account the user actually connected — NOT merely a Claude CLI
            # that happens to be installed. Detection is not consent.
            if conn.account_connected:
                # ...but a subscription still needs the CLI to actually run.
                # Reporting ready without it is what produced a 401 on the first
                # message the user sent.
                from .claude_code import find_claude
                if find_claude():
                    return True, ""
                return False, (
                    "Claude account connected, but running a Claude subscription "
                    "needs the Claude CLI. Install it (npm i -g "
                    "@anthropic-ai/claude-code) or add an ANTHROPIC_API_KEY."
                )
        except Exception:
            pass
        return False, "set ANTHROPIC_API_KEY or connect Claude account"

    def _subscription_backend(self) -> LLMProvider | None:
        """The Claude CLI, which is how a subscription runs inference."""
        if self._cli is None:
            from .claude_code import ClaudeCodeProvider, find_claude
            if not find_claude():
                return None
            # Pass the id through unchanged — the CLI accepts the same ids the
            # catalog uses (claude-opus-5, claude-sonnet-5, ...). Rewriting it
            # here produced names the CLI does not recognise.
            self._cli = ClaudeCodeProvider(model=self.model)
        return self._cli

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
        if not self.api_key:
            # Subscription, not an API key — the Messages API would 401.
            backend = self._subscription_backend()
            if backend is None:
                return ChatResult(text=(
                    "⚠️ No Anthropic API key, and the Claude CLI needed to run a "
                    "Claude subscription isn't installed. Add an API key in "
                    "Models & Accounts, or install the Claude CLI."))
            return backend.chat(messages, tools=tools, temperature=temperature,
                                max_tokens=max_tokens)

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

        try:
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
        except httpx.HTTPStatusError as exc:
            err = classify_http("claude", exc.response.status_code, exc.response.text,
                                model=self.model, key_env=self.key_env)
            return ChatResult(text=err.as_reply())
        except httpx.HTTPError as exc:
            err = classify_exception("claude", exc, model=self.model,
                                     base_url=self.base_url)
            return ChatResult(text=err.as_reply())

        try:
            data = resp.json()
            blocks = data.get("content", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            err = ProviderError(ErrorKind.BAD_REQUEST, "claude", model=self.model,
                                message="Unexpected response from Claude. "
                                        "Try again or switch models.")
            return ChatResult(text=err.as_reply())

        text_parts, calls = [], []
        for block in blocks:
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
