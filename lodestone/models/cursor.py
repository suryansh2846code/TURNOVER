"""Cursor provider via official Cursor API key or Cursor CLI.

Connects to Cursor's official API using CURSOR_API_KEY, or interfaces with the
official Cursor agent CLI if installed on the system.
No unofficial bridges, reverse-engineered tokens, or private desktop cookies.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import _saved_key
from .openai_compat import OpenAICompatProvider


def find_cursor_cli() -> str | None:
    """Find official Cursor CLI binary if installed."""
    for bin_name in ("cursor", "agent"):
        p = shutil.which(bin_name)
        if p:
            return p
    # Check standard Homebrew or application paths
    for cand in ("/opt/homebrew/bin/cursor", "/usr/local/bin/cursor",
                 os.path.expanduser("~/.local/bin/cursor"),
                 os.path.expanduser("~/.cursor/bin/agent")):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def get_cursor_cli_status() -> tuple[bool, str, str | None]:
    """Check official Cursor CLI authentication status."""
    cli = find_cursor_cli()
    if not cli:
        return False, "Cursor CLI not installed", None
    try:
        res = subprocess.run([cli, "status"], capture_output=True, text=True, timeout=3.0)
        output = (res.stdout or res.stderr or "").strip()
        if res.returncode == 0 and "Logged in" in output or "Authenticated" in output:
            email = None
            for line in output.splitlines():
                if "@" in line:
                    parts = line.split()
                    for p in parts:
                        if "@" in p and "." in p:
                            email = p.strip("<>(),;:")
                            break
            return True, output, email
        return False, output or "CLI not logged in (run 'agent login')", None
    except Exception as exc:
        return False, f"Cursor CLI check failed: {exc}", None


class CursorProvider(OpenAICompatProvider):
    name = "cursor"
    default_base = "https://api.cursor.com/v1"
    default_model = "cursor-small"
    key_env = "CURSOR_API_KEY"
    key_required = True

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        resolved_key = (
            api_key
            or os.environ.get("CURSOR_API_KEY")
            or _saved_key("CURSOR_API_KEY")
            or ""
        )
        resolved_base = (
            base_url
            or os.environ.get("CURSOR_BASE_URL")
            or os.environ.get("CURSOR_API_BASE")
            or self.default_base
        )
        super().__init__(model=model, api_key=resolved_key, base_url=resolved_base)

    def is_ready(self) -> tuple[bool, str]:
        # 1. API key authentication
        if self.api_key:
            return True, ""
        # 2. Connected account
        try:
            from .connections import ConnectionStatus, get_connection
            conn = get_connection("cursor")
            if conn.connection_status == ConnectionStatus.DISCONNECTED:
                return False, "Disconnected. Set CURSOR_API_KEY or sign in with Cursor"
            if conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED:
                return True, ""
        except Exception:
            pass
        # 3. Check official Cursor CLI login
        cli_ok, cli_msg, _ = get_cursor_cli_status()
        if cli_ok:
            return True, ""
        return False, "Sign in with Cursor or set CURSOR_API_KEY"
