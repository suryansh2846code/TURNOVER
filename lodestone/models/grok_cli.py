"""Grok provider via xAI's official CLI (`grok -p`).

xAI sells two separately-billed things: the developer API at `api.x.ai`, paid
for with credits from console.x.ai, and a SuperGrok subscription covering
grok.com and the apps. A subscription grants no API credits, so an OAuth
sign-in fails every `api.x.ai` request with 402
`personal-team-blocked:spending-limit`.

The sanctioned way to run a subscription is xAI's own agentic CLI, Grok Build:

    grok -p "<prompt>" --output-format json -m <model>

installed with `curl -fsSL https://x.ai/cli/install.sh | bash` (or
`npm i -g @xai-official/grok`) and signed in with `grok login`. The
`grok-cli:access` scope our OAuth token already carries is for exactly this.

Same shape as the Claude Code and Cursor backends: the CLI owns auth and
inference, and returns text rather than structured tool calls — so agents answer
from the context Lodestone injects rather than calling tools themselves.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from . import login_processes
from .base import ChatResult, LLMProvider, Message, parse_cli_json
from .cache import ttl_cached
from .errors import ErrorKind, ProviderError, classify_cli

# GUI-launched apps get a minimal PATH; the installer uses ~/.local/bin.
_EXTRA_BIN_DIRS = [
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".grok" / "bin"),
    str(Path.home() / ".npm-global" / "bin"),
]

INSTALL_HINT = (
    "Grok CLI not found. Install it with "
    "`curl -fsSL https://x.ai/cli/install.sh | bash` (or "
    "`npm i -g @xai-official/grok`), then run `grok login`."
)


def _augmented_path() -> str:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in _EXTRA_BIN_DIRS:
        if d and d not in parts and os.path.isdir(d):
            parts.append(d)
    return os.pathsep.join(parts)


def find_grok_cli() -> str | None:
    """Locate xAI's `grok` binary, verifying it is actually theirs."""
    # Our own managed copy wins: it is version-pinned and we installed it, so a
    # user never has to install anything by hand.
    from .cli_manager import managed_binary

    pinned = managed_binary("grok")
    if pinned:
        return str(pinned)

    candidates = []
    which = shutil.which("grok", path=_augmented_path())
    if which:
        candidates.append(which)
    for d in _EXTRA_BIN_DIRS:
        cand = Path(d) / "grok"
        if cand.exists() and os.access(cand, os.X_OK):
            candidates.append(str(cand))

    for path in candidates:
        try:
            res = subprocess.run([path, "--version"], capture_output=True, text=True,
                                 timeout=5.0,
                                 env={**os.environ, "PATH": _augmented_path()})
        except Exception:
            continue
        if "grok" in f"{res.stdout} {res.stderr}".lower():
            return path
    return None


@ttl_cached(120.0)
def grok_cli_models() -> list[str]:
    """Ask the CLI what this account can run — `grok models` prints e.g.

        Default model: grok-4.6

        Available models:
          * grok-4.6 (default)
          - grok-4.5
    """
    cli = find_grok_cli()
    if not cli:
        return []
    try:
        res = subprocess.run([cli, "models"], capture_output=True, text=True,
                             timeout=20.0, env={**os.environ, "PATH": _augmented_path()})
    except Exception:
        return []

    models: list[str] = []
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith(("*", "-")):
            continue
        name = line.lstrip("*- ").split()[0].strip()
        if name and name not in models:
            models.append(name)
    return models


_auth_cache: tuple[float, dict] | None = None
_AUTH_TTL = 3.0


def grok_cli_auth_status(*, fresh: bool = False) -> dict:
    """Whether the Grok CLI is signed in.

    `grok models` prints "You are not authenticated." when it is not, and the
    model list either way — so one call answers both questions.
    """
    global _auth_cache
    # Polled once a second during sign-in; without this every tick spawns a
    # subprocess and the request queue outruns the server.
    if not fresh and _auth_cache and (time.monotonic() - _auth_cache[0]) < _AUTH_TTL:
        return _auth_cache[1]

    cli = find_grok_cli()
    if not cli:
        result = {"installed": False, "authenticated": False}
        _auth_cache = (time.monotonic(), result)
        return result
    try:
        res = subprocess.run([cli, "models"], capture_output=True, text=True,
                             timeout=20.0, env={**os.environ, "PATH": _augmented_path()})
    except Exception:
        result = {"installed": True, "authenticated": False}
        _auth_cache = (time.monotonic(), result)
        return result
    blob = f"{res.stdout} {res.stderr}".lower()
    result = {
        "installed": True,
        "authenticated": "not authenticated" not in blob and res.returncode == 0,
    }
    _auth_cache = (time.monotonic(), result)
    return result


_login_proc: subprocess.Popen | None = None
_login_baseline: dict | None = None      # who was signed in when it started


def reset_login_state() -> None:
    """Forget any in-flight login (used on disconnect, and by tests)."""
    global _login_proc, _login_baseline
    _login_proc, _login_baseline = None, None


def reset_auth_cache() -> None:
    """Forget the cached sign-in state (used on login/cancel, and by tests)."""
    global _auth_cache
    _auth_cache = None


def login_progress() -> dict:
    """How an in-flight `login` is going.

    Completion is the CLI's process exiting, not the account merely looking
    authenticated: re-signing in while already signed in would otherwise report
    success on the first poll, before the user had touched the browser.
    """
    def _still_running(proc) -> bool:
        poll = getattr(proc, "poll", None)
        return callable(poll) and poll() is None

    baseline = _login_baseline or {}
    current = grok_cli_auth_status(fresh=_login_proc is not None and not _still_running(_login_proc))
    running = _still_running(_login_proc)
    changed_account = (
        bool(current.get("email")) and current.get("email") != baseline.get("email"))
    newly_authed = bool(current.get("authenticated")) and not baseline.get("authenticated")
    return {
        "in_flight": _login_proc is not None,
        "running": running,
        "authenticated": bool(current.get("authenticated")),
        "email": current.get("email"),
        # Either the process finished, or the account visibly changed under us.
        "done": bool(current.get("authenticated")) and (not running or changed_account or newly_authed),
    }


def cancel_cli_login() -> bool:
    """Stop an in-progress `login`. The browser tab stays open; the user simply
    never finishes, and nothing is recorded."""
    global _login_proc, _auth_cache, _login_baseline
    proc, _login_proc = _login_proc, None
    _login_baseline = None
    _auth_cache = None
    if proc is None or not callable(getattr(proc, "poll", None)) or proc.poll() is not None:
        return False
    try:
        proc.terminate()
        return True
    except Exception:
        return False
    finally:
        login_processes.release(getattr(proc, "pid", None))


def start_grok_cli_login() -> tuple[bool, str]:
    """Run the CLI's own browser sign-in (`grok login --oauth`).

    The OAuth client belongs to Grok Build, so this is the only way to reach
    that consent screen. Spawned detached; progress is observed by polling.
    """
    cli = find_grok_cli()
    if not cli:
        return False, INSTALL_HINT
    global _login_proc, _auth_cache, _login_baseline
    # Remember who was signed in before, so an existing session is not mistaken
    # for the sign-in we are about to start.
    _login_baseline = grok_cli_auth_status(fresh=True)
    _auth_cache = None      # the answer is about to change
    try:
        _login_proc = subprocess.Popen([cli, "login", "--oauth"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         env={**os.environ, "PATH": _augmented_path()},
                         start_new_session=True)
        login_processes.track(_login_proc, "login")
    except Exception as exc:
        return False, f"Could not start Grok sign-in: {exc}"
    return True, "Opened Grok sign-in in your browser."


class GrokCliProvider(LLMProvider):
    name = "grok-cli"
    model = "grok-4.6"

    def __init__(self, model: str | None = None, **_: object) -> None:
        self._bin = find_grok_cli()
        if model and model.lower().startswith("grok"):
            self.model = model

    def is_ready(self) -> tuple[bool, str]:
        if not self._bin:
            return False, INSTALL_HINT
        return True, ""

    def _prompt(self, messages: list[Message]) -> str:
        """`grok -p` takes one instruction, not a User:/Assistant: transcript, so
        system context and prior turns are folded into the prompt."""
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
        return f"{system}\n\n---\n\n{prompt}" if system else prompt

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        if not self._bin:
            return ChatResult(text=f"⚠️ {INSTALL_HINT}")

        from .cli_manager import agent_workspace

        workspace = agent_workspace()
        # Run in our own empty workspace: this is a coding agent and we only
        # want text back, so nothing of the user's is in reach.
        cmd = [self._bin, "-p", self._prompt(messages), "--output-format", "json",
               "--cwd", str(workspace)]
        if self.model:
            cmd += ["-m", self.model]
        env = {**os.environ, "PATH": _augmented_path()}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                  env=env, cwd=str(workspace))
        except subprocess.TimeoutExpired:
            return ChatResult(text=ProviderError(
                ErrorKind.TIMEOUT, "xai", model=self.model, retryable=True,
                message="Grok timed out. Try again, or switch model.").as_reply())

        data = parse_cli_json(proc.stdout)
        text = ""
        for key in ("result", "text", "response", "content", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text and not data:
            text = (proc.stdout or "").strip()

        if proc.returncode != 0 or data.get("is_error"):
            if text:
                return ChatResult(text=text, finish_reason="stop")
            err = classify_cli("xai", proc.returncode, proc.stdout or "",
                               proc.stderr or "", model=self.model)
            if err.kind is ErrorKind.AUTH:
                err.message = "The Grok CLI isn't signed in. Run `grok login`, then retry."
            return ChatResult(text=err.as_reply())
        return ChatResult(text=text, finish_reason="stop")
