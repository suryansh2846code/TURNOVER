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
import re
import shutil
import subprocess
import time
from pathlib import Path

from .base import ChatResult, LLMProvider, Message, _saved_key, parse_cli_json
from .cache import ttl_cached
from .errors import ErrorKind, ProviderError, classify_cli

# The installer puts `agent` here; GUI-launched apps get a minimal PATH.
_EXTRA_BIN_DIRS = [
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".cursor" / "bin"),
]


INSTALL_HINT = (
    "Cursor CLI ('agent') not found. Install it with "
    "`curl https://cursor.com/install -fsS | bash`, then sign in — Cursor "
    "has no chat API, so its models run through that CLI on your own plan."
)


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
    # Our own managed copy wins: it is version-pinned and we installed it, so a
    # user never has to install anything by hand.
    from .cli_manager import managed_binary

    pinned = managed_binary("cursor")
    if pinned:
        return str(pinned)

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


_auth_cache: tuple[float, dict] | None = None
_AUTH_TTL = 3.0


def cursor_cli_auth_status(*, fresh: bool = False) -> dict:
    """Ask the CLI whether it is signed in.

        agent status --format json
        -> {"status":"unauthenticated","isAuthenticated":false,"message":"Not logged in"}
    """
    global _auth_cache
    # Polled once a second during sign-in; without this every tick spawns a
    # subprocess and the request queue outruns the server.
    if not fresh and _auth_cache and (time.monotonic() - _auth_cache[0]) < _AUTH_TTL:
        return _auth_cache[1]

    cli = find_cursor_cli()
    if not cli:
        result = {"installed": False, "authenticated": False}
        _auth_cache = (time.monotonic(), result)
        return result
    try:
        res = subprocess.run([cli, "status", "--format", "json"],
                             capture_output=True, text=True, timeout=15.0,
                             env={**os.environ, "PATH": _augmented_path()})
    except Exception:
        result = {"installed": True, "authenticated": False}
        _auth_cache = (time.monotonic(), result)
        return result

    data = parse_cli_json(res.stdout) or {}
    # Identity lives under `userInfo`:
    #   {"status":"authenticated","isAuthenticated":true,
    #    "userInfo":{"email":"…","firstName":"…","lastName":"…"}}
    info = data.get("userInfo") or {}
    name = " ".join(p for p in (info.get("firstName"), info.get("lastName")) if p)
    result = {
        "installed": True,
        "authenticated": bool(data.get("isAuthenticated")),
        "email": info.get("email") or data.get("email") or None,
        "name": name or None,
        "message": data.get("message") or "",
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
    current = cursor_cli_auth_status(fresh=_login_proc is not None and not _still_running(_login_proc))
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


def start_cursor_cli_login() -> tuple[bool, str]:
    """Run the CLI's own browser sign-in.

    `agent login` opens authenticator.cursor.sh itself — the OAuth client
    belongs to the CLI, so this is the only way to reach that flow. It is
    spawned detached; progress is observed by polling `agent status`.
    """
    cli = find_cursor_cli()
    if not cli:
        return False, INSTALL_HINT
    global _login_proc, _auth_cache, _login_baseline
    # Remember who was signed in before, so an existing session is not mistaken
    # for the sign-in we are about to start.
    _login_baseline = cursor_cli_auth_status(fresh=True)
    _auth_cache = None      # the answer is about to change
    try:
        _login_proc = subprocess.Popen([cli, "login"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         env={**os.environ, "PATH": _augmented_path()},
                         start_new_session=True)
    except Exception as exc:
        return False, f"Could not start Cursor sign-in: {exc}"
    return True, "Opened Cursor sign-in in your browser."


def get_cursor_cli_status() -> tuple[bool, str, str | None]:
    """(signed in, message, email) — kept for existing account detection."""
    st = cursor_cli_auth_status()
    if not st["installed"]:
        return False, "Cursor CLI not installed", None
    return st["authenticated"], st.get("message") or "", st.get("email")


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@ttl_cached(120.0)
def cursor_cli_models() -> list[tuple[str, str]]:
    """(id, label) pairs from `agent --list-models` — the account's own list.

    The hardcoded catalog here was invented (`cursor-fast`, `cursor-small`,
    `claude-sonnet-5`); none of those exist, and the CLI rejects them.
    """
    cli = find_cursor_cli()
    if not cli:
        return []
    try:
        res = subprocess.run([cli, "--list-models"], capture_output=True, text=True,
                             timeout=30.0, env={**os.environ, "PATH": _augmented_path()})
    except Exception:
        return []

    out = []
    for line in _ANSI.sub("", res.stdout or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("available models"):
            continue
        mid, _, label = line.partition(" - ")
        mid = mid.strip()
        if mid and " " not in mid:
            out.append((mid, label.strip() or mid))
    return out


class CursorProvider(LLMProvider):
    name = "cursor"
    model = "auto"
    key_env = "CURSOR_API_KEY"

    _INSTALL_HINT = INSTALL_HINT

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

        from .cli_manager import agent_workspace

        workspace = agent_workspace()
        # --trust: the prompt "Do you trust the contents of this directory?"
        #   blocks on stdin and hangs a headless call. The workspace is ours and
        #   empty, so trusting it grants nothing.
        # No --force/--yolo: we want an answer, not shell access.
        # Always pass --model, including "auto": the CLI persists the last model
        # selected, so omitting the flag does NOT mean Auto — it means whatever
        # was chosen last, which a Free plan then refuses.
        cmd = [self._bin, "-p", prompt, "--output-format", "json",
               "--trust", "--workspace", str(workspace),
               "--model", self.model or "auto"]

        env = {**os.environ, "PATH": _augmented_path()}
        if self.api_key:
            env["CURSOR_API_KEY"] = self.api_key
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=180, env=env, cwd=str(workspace))
        except subprocess.TimeoutExpired:
            return ChatResult(text=ProviderError(
                ErrorKind.TIMEOUT, "cursor", model=self.model, retryable=True,
                message="Cursor timed out. Try again, or switch model.").as_reply())

        data = parse_cli_json(proc.stdout)
        text = (data.get("result") or data.get("text") or "").strip()

        if proc.returncode != 0 or data.get("is_error"):
            if text:
                return ChatResult(text=text, finish_reason="stop")
            blob = f"{proc.stdout} {proc.stderr}"
            err = classify_cli("cursor", proc.returncode,
                               proc.stdout or str(data.get("subtype") or ""),
                               proc.stderr or "", model=self.model)
            if "Named models unavailable" in blob or "can only use Auto" in blob:
                err.kind = ErrorKind.MODEL_NOT_ENTITLED
                err.message = (f"`{self.model}` isn't included in your Cursor plan — "
                               "free plans can only use **Auto**. Pick Auto in the "
                               "model selector, or upgrade your Cursor plan.")
            elif err.kind is ErrorKind.AUTH:
                err.message = "The Cursor CLI isn't signed in. Run `agent login`, then retry."
            return ChatResult(text=err.as_reply())
        return ChatResult(text=text or proc.stdout.strip(), finish_reason="stop")
