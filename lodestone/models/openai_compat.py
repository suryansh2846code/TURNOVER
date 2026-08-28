"""OpenAI-compatible provider.

One implementation covers OpenAI, OpenRouter, Ollama, vLLM, llama.cpp, LM
Studio, and any other server that speaks the /chat/completions API with tool
calling — differing only in base URL, key and default model.
"""
from __future__ import annotations

import json
import os
import uuid

import httpx

from .base import ChatResult, LLMProvider, Message, Tool, ToolCall


class OpenAICompatProvider(LLMProvider):
    name = "openai"
    default_base = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
    key_env = "OPENAI_API_KEY"
    key_required = True

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        self.model = model or os.environ.get(
            f"{self.name.upper()}_MODEL", self.default_model
        )
        self.api_key = api_key or os.environ.get(self.key_env, "")
        self.base_url = (base_url or os.environ.get(
            f"{self.name.upper()}_BASE_URL", self.default_base
        )).rstrip("/")

    def is_ready(self) -> tuple[bool, str]:
        if self.key_required and not self.api_key:
            return False, f"set {self.key_env}"
        return True, ""

    def _to_openai(self, messages: list[Message]) -> list[dict]:
        out = []
        for m in messages:
            if m.role == "tool":
                out.append({
                    "role": "tool", "tool_call_id": m.tool_call_id,
                    "content": m.content,
                })
            elif m.role == "assistant" and m.tool_calls:
                out.append({
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [{
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.name,
                                     "arguments": json.dumps(tc.arguments)},
                    } for tc in m.tool_calls],
                })
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        payload = {
            "model": self.model,
            "messages": self._to_openai(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            } for t in tools]

        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]["message"]
        calls = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(
                id=tc.get("id", str(uuid.uuid4())),
                name=tc["function"]["name"], arguments=args,
            ))
        return ChatResult(
            text=choice.get("content") or "",
            tool_calls=calls,
            raw=data,
            finish_reason=data["choices"][0].get("finish_reason", "stop"),
        )


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    default_base = "https://openrouter.ai/api/v1"
    default_model = "anthropic/claude-3.5-sonnet"
    key_env = "OPENROUTER_API_KEY"
    key_required = True


class OllamaProvider(OpenAICompatProvider):
    """Local models via Ollama — fully offline, no key."""
    name = "ollama"
    default_base = "http://localhost:11434/v1"
    default_model = "llama3.1"
    key_env = "OLLAMA_API_KEY"
    key_required = False

    def is_ready(self) -> tuple[bool, str]:
        try:
            httpx.get(self.base_url.replace("/v1", "") + "/api/tags", timeout=2)
            return True, ""
        except Exception:
            return False, "Ollama not running on localhost:11434"
