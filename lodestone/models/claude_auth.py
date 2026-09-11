"""Claude Code CLI OAuth and Account Manager for TURNOVER.

Spawns the Claude CLI OAuth login process (`claude auth login --claudeai`),
extracts the official Claude consent authorization URL, watches ~/.claude.json
for live credential updates, and supports submitting an authorization code.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connections import ConnectionStatus, get_connection, save_connection

logger = logging.getLogger(__name__)


def _claude_json_path() -> Path:
    return Path.home() / ".claude.json"


def find_claude_cli() -> Path | None:
    which_p = shutil.which("claude")
    if which_p:
        return Path(which_p)
    candidates = [
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        Path.home() / ".local/bin/claude",
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return None


class _ClaudeAuthState:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.auth_url: str = ""
        self.status: str = "idle"  # idle | waiting | success | error
        self.error_message: str = ""
        self.connected_email: str = ""
        self.started_at: float = 0


_GLOBAL_CLAUDE_AUTH_STATE = _ClaudeAuthState()


def _watch_claude_json_async(initial_mtime: float):
    def _watcher():
        p = _claude_json_path()
        for _ in range(150):  # up to 3 mins
            time.sleep(1.2)
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
                if mtime > initial_mtime:
                    data = json.loads(p.read_text())
                    oa = data.get("oauthAccount") or {}
                    email = oa.get("emailAddress")
                    name = oa.get("displayName") or oa.get("fullName") or "Claude User"
                    if email:
                        now = datetime.now(timezone.utc).isoformat()
                        conn = get_connection("claude")
                        conn.auth_method = "account"
                        conn.email = email
                        conn.account_display_name = name
                        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
                        conn.status_message = f"Connected to Claude Pro ({email})"
                        conn.connected_at = conn.connected_at or now
                        conn.last_verified_at = now
                        save_connection(conn)

                        with _GLOBAL_CLAUDE_AUTH_STATE.lock:
                            _GLOBAL_CLAUDE_AUTH_STATE.status = "success"
                            _GLOBAL_CLAUDE_AUTH_STATE.connected_email = email
                        logger.info(f"Claude authenticated successfully as {email}")
                        break
            except Exception as exc:
                logger.debug(f"Watching claude.json: {exc}")

    t = threading.Thread(target=_watcher, daemon=True)
    t.start()


def start_claude_login_flow() -> tuple[bool, str, str]:
    """Start Claude login via CLI, extract auth URL and watch ~/.claude.json."""
    claude_cli = find_claude_cli()
    p_json = _claude_json_path()
    initial_mtime = p_json.stat().st_mtime if p_json.exists() else 0.0

    fallback_url = "https://claude.ai/login"

    if not claude_cli:
        return True, fallback_url, "Opened Claude sign-in in browser"

    with _GLOBAL_CLAUDE_AUTH_STATE.lock:
        # Kill previous process if still active
        if _GLOBAL_CLAUDE_AUTH_STATE.proc:
            try:
                _GLOBAL_CLAUDE_AUTH_STATE.proc.terminate()
            except Exception:
                pass
            _GLOBAL_CLAUDE_AUTH_STATE.proc = None

        try:
            proc = subprocess.Popen(
                [str(claude_cli), "auth", "login"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
            )
            _GLOBAL_CLAUDE_AUTH_STATE.proc = proc
            _GLOBAL_CLAUDE_AUTH_STATE.status = "waiting"
            _GLOBAL_CLAUDE_AUTH_STATE.started_at = time.time()
            _GLOBAL_CLAUDE_AUTH_STATE.error_message = ""
            _GLOBAL_CLAUDE_AUTH_STATE.connected_email = ""
        except Exception as exc:
            logger.warning(f"Could not start claude CLI: {exc}")
            return True, fallback_url, "Opened Claude in browser"

    # Extract auth URL from stdout in a reader thread
    found_url = [None]

    def _read_output():
        try:
            for line in proc.stdout:
                m = re.search(r"(https://claude\.com/cai/oauth/authorize\S+)", line)
                if m:
                    found_url[0] = m.group(1)
                    with _GLOBAL_CLAUDE_AUTH_STATE.lock:
                        _GLOBAL_CLAUDE_AUTH_STATE.auth_url = found_url[0]
                    break
        except Exception:
            pass

    reader_thread = threading.Thread(target=_read_output, daemon=True)
    reader_thread.start()
    reader_thread.join(timeout=3.0)

    auth_url = found_url[0] or _GLOBAL_CLAUDE_AUTH_STATE.auth_url or fallback_url
    _watch_claude_json_async(initial_mtime)

    return True, auth_url, "Opened Claude authorization in browser"


def submit_claude_auth_code(code: str) -> tuple[bool, str]:
    """Pass an authorization code (code#state) to the waiting Claude CLI."""
    with _GLOBAL_CLAUDE_AUTH_STATE.lock:
        proc = _GLOBAL_CLAUDE_AUTH_STATE.proc

    if not proc or proc.poll() is not None:
        return False, "No active Claude login process waiting for code"

    try:
        proc.stdin.write(code.strip() + "\n")
        proc.stdin.flush()
        # Wait up to 5s for ~/.claude.json update
        time.sleep(2.0)
        p = _claude_json_path()
        if p.exists():
            data = json.loads(p.read_text())
            email = data.get("oauthAccount", {}).get("emailAddress")
            if email:
                return True, f"Successfully authenticated as {email}"
        return True, "Code submitted, finalizing connection..."
    except Exception as exc:
        return False, f"Failed to submit code: {exc}"


def get_claude_auth_status() -> dict[str, Any]:
    with _GLOBAL_CLAUDE_AUTH_STATE.lock:
        return {
            "status": _GLOBAL_CLAUDE_AUTH_STATE.status,
            "error": _GLOBAL_CLAUDE_AUTH_STATE.error_message,
            "email": _GLOBAL_CLAUDE_AUTH_STATE.connected_email,
            "auth_url": _GLOBAL_CLAUDE_AUTH_STATE.auth_url,
        }
