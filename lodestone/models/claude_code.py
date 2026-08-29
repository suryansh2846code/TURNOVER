"""Claude Code provider — run agents on your terminal Claude (`claude -p`).

This uses the Claude Code CLI already installed on your machine as the model
backend, so Lodestone's agents reason with Claude using your existing Claude
auth — no separate API key wired into Lodestone.

Trade-off: Claude Code headless returns text, not our structured tool-calls. So
with this backend the agent answers from the context Lodestone already injects
(auto-recalled brain facts, the date, your current tasks) rather than calling
search_brain/add_task itself. That's fine: recall still makes it "know you", and
the deterministic Tasks panel handles task actions. Each call uses your Claude
usage, so it is not free like the local Ollama backend.
"""
from __future__ import annotations

import json
import shutil
import subprocess

from .base import ChatResult, LLMProvider, Message


class ClaudeCodeProvider(LLMProvider):
    name = "claude-code"
    model = "claude-code"

    def __init__(self, model: str | None = None, **_: object) -> None:
        self._bin = shutil.which("claude")
        # Only honor a model name that is actually a Claude model — the global
        # LODESTONE_MODEL_NAME may be set for another backend (e.g. an Ollama tag).
        if model and any(k in model.lower()
                         for k in ("claude", "haiku", "sonnet", "opus", "fable")):
            self.model = model
        # else keep default "claude-code" → let Claude Code pick its default model

    def is_ready(self) -> tuple[bool, str]:
        if not self._bin:
            return False, "Claude Code CLI ('claude') not found on PATH"
        return True, ""

    def _flatten(self, messages: list[Message]) -> str:
        parts: list[str] = []
        for m in messages:
            if m.role == "system":
                parts.append(m.content)
            elif m.role == "user":
                parts.append(f"User: {m.content}")
            elif m.role == "assistant" and m.content:
                parts.append(f"Assistant: {m.content}")
            elif m.role == "tool":
                parts.append(f"[tool result] {m.content}")
        parts.append("Assistant:")
        return "\n\n".join(parts)

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        if not self._bin:
            return ChatResult(text="Claude Code CLI not available.")
        prompt = self._flatten(messages)
        cmd = [self._bin, "-p", "--output-format", "json"]
        if self.model and self.model != "claude-code":
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            return ChatResult(text="(Claude Code timed out.)")
        if proc.returncode != 0:
            return ChatResult(text=f"(Claude Code error: {proc.stderr.strip()[:300]})")
        try:
            data = json.loads(proc.stdout)
            text = data.get("result") or ""
        except json.JSONDecodeError:
            text = proc.stdout.strip()
        return ChatResult(text=text.strip(), finish_reason="stop")
