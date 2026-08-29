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

    def _split(self, messages: list[Message]) -> tuple[str, str]:
        """Return (system_prompt, user_prompt).

        Claude Code's `-p` expects a real instruction, not a fake User:/Assistant:
        transcript (that trips its stop-sequence handling and errors out). So we
        send the latest user message as the prompt, and everything else — our
        system instructions, injected brain/date/task context, and prior turns —
        via --append-system-prompt.
        """
        system_parts = [m.content for m in messages if m.role == "system" and m.content]
        convo = [m for m in messages if m.role in ("user", "assistant", "tool")]
        last_user = next((m for m in reversed(convo) if m.role == "user"), None)
        prompt = last_user.content if last_user else ""
        prior = convo[: convo.index(last_user)] if last_user in convo else convo
        hist = "\n".join(
            f"{'User' if m.role == 'user' else 'Assistant' if m.role == 'assistant' else 'Tool'}: {m.content}"
            for m in prior if m.content
        )
        if hist:
            system_parts.append("Recent conversation so far:\n" + hist)
        return "\n\n".join(system_parts), prompt

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        if not self._bin:
            return ChatResult(text="Claude Code CLI not available.")
        system_prompt, prompt = self._split(messages)
        cmd = [self._bin, "-p", "--output-format", "json"]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        if self.model and self.model != "claude-code":
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            return ChatResult(text="⚠️ Claude Code timed out. Try again or switch model.")

        data = {}
        if proc.stdout.strip().startswith("{"):
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = {}
        text = (data.get("result") or "").strip()

        if proc.returncode != 0 or data.get("is_error"):
            if text:                       # Claude returned a usable message anyway
                return ChatResult(text=text, finish_reason="stop")
            detail = (proc.stderr.strip() or data.get("subtype")
                      or data.get("stop_reason") or "unknown error")
            return ChatResult(
                text=f"⚠️ Claude Code couldn't answer ({detail}). "
                     "Try rephrasing, or switch to a different model in the sidebar.")
        return ChatResult(text=text or proc.stdout.strip(), finish_reason="stop")
