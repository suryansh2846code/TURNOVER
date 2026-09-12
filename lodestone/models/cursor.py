"""Cursor provider — runs agents through the Cursor CLI (`agent -p`).

Cursor does **not** expose a chat-completions API. `api.cursor.com` carries the
admin/agent surface (`/v1/models` answers "Invalid User API Key"), but
`POST /v1/chat/completions` is a 404 — that route does not exist. So this is not
an OpenAI-compatible provider, and pointing one at api.cursor.com fails on every
message no matter how valid the key is.

The supported way to run Cursor's models programmatically is its headless CLI:

    agent -p "<prompt>" --output-format json --model <model>

installed with `curl https://cursor.com/install -fsS | bash`. `CURSOR_API_KEY`
authenticates *that CLI*; it is not a REST credential. Inference therefore runs
on the user's own Cursor plan, exactly like the Claude Code backend.

Trade-off (same as Claude Code): the CLI returns text, not structured tool
calls, so agents answer from the context Lodestone injects rather than calling
tools themselves.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import ChatResult, LLMProvider, Message, _saved_key, parse_cli_json
from .errors import ErrorKind, ProviderError, classify_cli

# The installer puts `agent` here; GUI-launched apps get a minimal PATH.
_EXTRA_BIN_DIRS = [
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".cursor" / "bin"),
]


def _augmented_path() -> str:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in _EXTRA_BIN_DIRS:
        if d and d not in parts and os.path.isdir(d):
            parts.append(d)
    return os.pathsep.join(parts)


def find_cursor_cli() -> str | None:
    """Locate Cursor's `agent` binary.

    `agent` is a generic name, so a bare PATH hit is verified before being
    trusted — the previous implementation would happily return any unrelated
    `agent` on PATH, or the `cursor` editor launcher, neither of which speaks
    the headless protocol.
    """
    candidates: list[str] = []
    which = shutil.which("cursor-agent", path=_augmented_path())
    if which:
        candidates.append(which)
    which = shutil.which("agent", path=_augmented_path())
    if which:
        candidates.append(which)
    for d in _EXTRA_BIN_DIRS:
        for name in ("cursor-agent", "agent"):
            cand = Path(d) / name
            if cand.exists() and os.access(cand, os.X_OK):
                candidates.append(str(cand))

    for path in candidates:
        if _is_cursor_agent(path):
            return path
    return None


def _is_cursor_agent(path: str) -> bool:
    """Confirm a binary really is Cursor's agent, not a name collision."""
    try:
        res = subprocess.run([path, "--version"], capture_output=True, text=True,
                             timeout=5.0, env={**os.environ, "PATH": _augmented_path()})
    except Exception:
        return False
    blob = f"{res.stdout} {res.stderr}".lower()
    if "cursor" in blob:
        return True
    # Some builds print a bare version; accept it only from Cursor's own paths.
    return res.returncode == 0 and "cursor" in path.lower()


def get_cursor_cli_status() -> tuple[bool, str, str | None]:
    """(installed, message, email). Auth is reported by the CLI on first use."""
    cli = find_cursor_cli()
    if not cli:
        return False, "Cursor CLI not installed", None
    return True, f"Cursor CLI found at {cli}", None


class CursorProvider(LLMProvider):
    name = "cursor"
    model = "cursor-fast"
    key_env = "CURSOR_API_KEY"

    _INSTALL_HINT = (
        "Cursor CLI ('agent') not found. Install it with "
        "`curl https://cursor.com/install -fsS | bash`, then sign in — Cursor "
        "has no chat API, so its models run through that CLI on your own plan."
    )

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 **_: object) -> None:
        self._bin = find_cursor_cli()
        self.api_key = (api_key if api_key is not None
                        else os.environ.get("CURSOR_API_KEY", "") or _saved_key("CURSOR_API_KEY"))
        if model:
            self.model = model

    def is_ready(self) -> tuple[bool, str]:
        # An API key alone cannot run inference — there is no endpoint to call.
        if not self._bin:
            return False, self._INSTALL_HINT
        return True, ""

    def _prompt(self, messages: list[Message]) -> tuple[str, str]:
        """(system context, prompt). `agent -p` wants an instruction, not a
        User:/Assistant: transcript, so prior turns go into the context block."""
        system = "\n\n".join(m.content for m in messages
                             if m.role == "system" and m.content)
        convo = [m for m in messages if m.role in ("user", "assistant", "tool")]
        last_user = next((m for m in reversed(convo) if m.role == "user"), None)
        prompt = last_user.content if last_user else ""
        prior = convo[: convo.index(last_user)] if last_user in convo else convo
        hist = "\n".join(
            f"{'User' if m.role == 'user' else 'Assistant' if m.role == 'assistant' else 'Tool'}: {m.content}"
            for m in prior if m.content
        )
        if hist:
            system = (system + "\n\nRecent conversation so far:\n" + hist).strip()
        return system, prompt

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        if not self._bin:
            return ChatResult(text=f"⚠️ {self._INSTALL_HINT}")

        system, prompt = self._prompt(messages)
        if system:
            prompt = f"{system}\n\n---\n\n{prompt}"

        cmd = [self._bin, "-p", prompt, "--output-format", "json"]
        if self.model and self.model not in ("cursor", "cursor-small"):
            cmd += ["--model", self.model]

        env = {**os.environ, "PATH": _augmented_path()}
        if self.api_key:
            env["CURSOR_API_KEY"] = self.api_key
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=180, env=env)
        except subprocess.TimeoutExpired:
            return ChatResult(text=ProviderError(
                ErrorKind.TIMEOUT, "cursor", model=self.model, retryable=True,
                message="Cursor timed out. Try again, or switch model.").as_reply())

        data = parse_cli_json(proc.stdout)
        text = (data.get("result") or data.get("text") or "").strip()

        if proc.returncode != 0 or data.get("is_error"):
            if text:
                return ChatResult(text=text, finish_reason="stop")
            err = classify_cli("cursor", proc.returncode,
                               proc.stdout or str(data.get("subtype") or ""),
                               proc.stderr or "", model=self.model)
            if err.kind is ErrorKind.AUTH:
                err.message = "The Cursor CLI isn't signed in. Run `agent login`, then retry."
            return ChatResult(text=err.as_reply())
        return ChatResult(text=text or proc.stdout.strip(), finish_reason="stop")
