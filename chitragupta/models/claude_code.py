"""Claude Code provider — run agents on your terminal Claude (`claude -p`).

This uses the Claude Code CLI already installed on your machine as the model
backend, so Chitragupta's agents reason with Claude using your existing Claude
auth — no separate API key wired into Chitragupta.

Trade-off: Claude Code headless returns text, not our structured tool-calls. So
with this backend the agent answers from the context Chitragupta already injects
(auto-recalled brain facts, the date, your current tasks) rather than calling
search_brain/add_task itself. That's fine: recall still makes it "know you", and
the deterministic Tasks panel handles task actions. Each call uses your Claude
usage, so it is not free like the local Ollama backend.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..log import get_logger
from .base import ChatResult, LLMProvider, Message, parse_cli_json
from .cli_login import augmented_path
from .errors import ErrorKind, ProviderError, classify_cli

log = get_logger(__name__)

# Bin dirs GUI apps miss: apps launched from Finder/.app get a minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin), so Homebrew, npm-global and the Claude Code
# local install are invisible to shutil.which. Search them explicitly.
_EXTRA_BIN_DIRS = [
    "/opt/homebrew/bin", "/usr/local/bin",
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / ".claude" / "local"),
    str(Path.home() / ".npm-global" / "bin"),
    str(Path.home() / "bin"),
    "/opt/homebrew/sbin",
]


def _augmented_path() -> str:
    return augmented_path(_EXTRA_BIN_DIRS)


def find_claude() -> str | None:
    """Locate the `claude` binary even when PATH is the stripped GUI default."""
    found = shutil.which("claude", path=_augmented_path())
    if found:
        return found
    for d in _EXTRA_BIN_DIRS:
        cand = Path(d) / "claude"
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
    return None


class ClaudeCodeProvider(LLMProvider):
    name = "claude-code"
    model = "claude-code"

    def __init__(self, model: str | None = None, **_: object) -> None:
        self._bin = find_claude()
        # Only honor a model name that is actually a Claude model — the global
        # CHITRAGUPTA_MODEL_NAME may be set for another backend (e.g. an Ollama tag).
        if model and any(k in model.lower()
                         for k in ("claude", "haiku", "sonnet", "opus", "fable")):
            self.model = model
        # else keep default "claude-code" → let Claude Code pick its default model

    def is_ready(self) -> tuple[bool, str]:
        if not self._bin:
            return False, ("Claude Code CLI ('claude') not found. Install it "
                           "(npm i -g @anthropic-ai/claude-code or brew install "
                           "claude-code), or pick another model in the dropdown.")
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


    def _stream_command(self, messages, tools):
        """`claude -p --output-format stream-json` — verified against the real
        CLI: it wraps Anthropic Messages events under `{"type":"stream_event"}`,
        and `--verbose` is required for the streaming format to be emitted."""
        system_prompt, prompt = self._split(messages)
        cmd = [self._bin, "-p", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages"]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        if self.model and self.model != "claude-code":
            cmd += ["--model", self.model]
        return cmd, prompt, {**os.environ, "PATH": _augmented_path()}

    def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        """Stream by asking the CLI for incremental events.

        All three vendor CLIs emit Anthropic Messages events, one JSON object
        per line, so `streaming.anthropic_events` parses them all.

        If the stream produces no text at all — an older CLI that does not know
        the flag, a format that has moved — nothing has been yielded yet, so the
        plain call runs instead and the user gets an answer rather than silence.
        Falling back *after* emitting text would duplicate it, which is why the
        decision hangs on whether any arrived.
        """
        from .streaming import from_result, stream_cli

        cmd, stdin, env = self._stream_command(messages, tools)
        if cmd is None:
            yield from from_result(self.chat(messages, tools=tools,
                                             temperature=temperature,
                                             max_tokens=max_tokens))
            return

        saw_text = False
        done = None
        try:
            for event in stream_cli(cmd, env=env, stdin=stdin,
                                    provider=self.name):
                if event.kind == "text" and event.text:
                    saw_text = True
                    yield event
                elif event.kind == "done":
                    done = event
        except Exception as exc:
            log.debug("%s streaming failed: %s", self.name, exc)
            saw_text = False

        if saw_text and done is not None and done.result is not None:
            yield done
            return
        yield from from_result(self.chat(messages, tools=tools,
                                         temperature=temperature,
                                         max_tokens=max_tokens))

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        if not self._bin:
            return ChatResult(text="Claude Code CLI not available.")

        from .accounts import detect_claude_account
        from .entitlements import evaluate_model_entitlement

        acct = detect_claude_account()
        user_plan = acct.get("plan")
        context = {"disabled_models": acct.get("disabled_models", {})}
        if self.model and self.model != "claude-code":
            locked, plan_req = evaluate_model_entitlement(
                provider="claude-code",
                model_id=self.model,
                is_connected=True,
                user_plan=user_plan,
                context=context,
            )
            if locked:
                return ChatResult(
                    text=f"⚠️ Model `{self.model}` is currently locked ({plan_req}). "
                         "Please select an unlocked model (such as Claude Opus 5 or Claude Sonnet 5) in the model selector.",
                    finish_reason="stop",
                )
        system_prompt, prompt = self._split(messages)
        cmd = [self._bin, "-p", "--output-format", "json"]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        if self.model and self.model != "claude-code":
            cmd += ["--model", self.model]
        env = {**os.environ, "PATH": _augmented_path()}
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ChatResult(text=ProviderError(
                ErrorKind.TIMEOUT, "claude-code", model=self.model, retryable=True,
                message="Claude Code timed out. Try again, or switch model.").as_reply())

        data = parse_cli_json(proc.stdout)
        text = (data.get("result") or "").strip()

        if proc.returncode != 0 or data.get("is_error"):
            if text:                       # Claude returned a usable message anyway
                return ChatResult(text=text, finish_reason="stop")
            err = classify_cli("claude-code", proc.returncode,
                               proc.stdout or str(data.get("subtype") or ""),
                               proc.stderr or "", model=self.model)
            return ChatResult(text=err.as_reply())
        return ChatResult(text=text or proc.stdout.strip(), finish_reason="stop")
