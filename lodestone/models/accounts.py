"""Local account detection and binding for AI providers (Google, Claude, Cursor, OpenAI, xAI).

Discovers and safely bridges accounts found on this computer:
- Google: via ~/.lodestone/google_token.json and google_account.json
- Claude / Anthropic: via ~/.claude.json (Claude Code / Anthropic OAuth session)
- Cursor: via Cursor global storage state.vscdb (cursorAuth/cachedEmail, accessToken)
- OpenAI / ChatGPT: via OpenAI config / stored credentials
- xAI: via saved developer credentials

Credentials are NEVER exposed or duplicated into logs or memory.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connections import ConnectionStatus, ProviderConnection, get_connection, save_connection


def detect_google_account() -> dict[str, Any]:
    """Detect signed-in Google account for Gemini."""
    try:
        from ..connectors.google_auth import _token_path, connected_email
        if _token_path().exists():
            email = connected_email(fetch=False) or "Google Account"
            return {
                "provider": "gemini",
                "connected": True,
                "email": email,
                "name": "Google Account",
                "plan": "Google Gemini",
                "auth_method": "account",
                "found_on_computer": True,
            }
    except Exception:
        pass
    return {"provider": "gemini", "connected": False, "found_on_computer": False}


def detect_claude_account() -> dict[str, Any]:
    """Detect Claude Pro / Anthropic account found on this computer (e.g. Claude Code CLI)."""
    conn = get_connection("claude")
    is_disconnected = (conn.connection_status == ConnectionStatus.DISCONNECTED)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    candidates = [
        Path(config_dir) / ".claude.json" if config_dir else None,
        Path.home() / ".claude.json",
        Path.home() / ".claude/claude.json",
    ]
    for p in candidates:
        if not p or not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
            oa = data.get("oauthAccount") or {}
            email = oa.get("emailAddress")
            if email:
                org_type = (oa.get("organizationType") or "").lower()
                if "enterprise" in org_type:
                    plan = "Claude Enterprise"
                elif "team" in org_type:
                    plan = "Claude Team"
                elif "pro" in org_type:
                    plan = "Claude Pro"
                else:
                    plan = "Claude Free"

                name = oa.get("displayName") or oa.get("fullName") or "Claude User"
                disabled_models: dict[str, str] = {}
                for opt in data.get("additionalModelOptionsCache") or []:
                    if isinstance(opt, dict) and opt.get("disabled"):
                        val = opt.get("value") or opt.get("label") or ""
                        disabled_models[val] = opt.get("description") or "Update Required"

                return {
                    "provider": "claude",
                    "connected": False if is_disconnected else (conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED),
                    "email": email,
                    "name": name,
                    "plan": plan,
                    "auth_method": "account",
                    "found_on_computer": True,
                    "disabled_models": disabled_models,
                }
        except Exception:
            pass
    return {"provider": "claude", "connected": False, "found_on_computer": False}


def detect_cursor_account() -> dict[str, Any]:
    """Detect Cursor account found in Cursor's local globalStorage across macOS, Linux, and Windows."""
    conn = get_connection("cursor")
    is_disconnected = (conn.connection_status == ConnectionStatus.DISCONNECTED)
    candidates = [
        Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb",
        Path.home() / ".config/Cursor/User/globalStorage/state.vscdb",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Cursor/User/globalStorage/state.vscdb")

    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn_sql = sqlite3.connect(str(db_path))
            rows = dict(conn_sql.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'cursorAuth/%'").fetchall())
            email = rows.get("cursorAuth/cachedEmail")
            membership = (rows.get("cursorAuth/stripeMembershipType") or "free").lower()
            token = rows.get("cursorAuth/accessToken")
            if email:
                if "pro" in membership:
                    plan = "Cursor Pro"
                elif any(k in membership for k in ("business", "enterprise")):
                    plan = "Cursor Business"
                else:
                    plan = "Cursor Free"

                return {
                    "provider": "cursor",
                    "connected": False if is_disconnected else (conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED or bool(token)),
                    "email": email,
                    "name": "Cursor User",
                    "plan": plan,
                    "auth_method": "account",
                    "found_on_computer": True,
                    "has_token": bool(token),
                }
        except Exception:
            pass
    return {"provider": "cursor", "connected": False, "found_on_computer": False}


def detect_openai_account() -> dict[str, Any]:
    """Detect OpenAI connection or ChatGPT subscription state."""
    conn = get_connection("openai")
    is_disconnected = (conn.connection_status == ConnectionStatus.DISCONNECTED)

    local = None
    try:
        from .chatgpt_auth import detect_chatgpt_local_session
        local = detect_chatgpt_local_session(fetch_usage=True)
    except Exception:
        pass

    if not is_disconnected and conn.email and conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
        plan = (local.get("plan") if local else None) or ("ChatGPT Free" if conn.auth_method == "account" else "OpenAI Developer")
        usage = local.get("usage") if local else None
        return {
            "provider": "openai",
            "connected": True,
            "email": conn.email or (local.get("email") if local else "OpenAI User"),
            "name": conn.account_display_name or (local.get("name") if local else "OpenAI Account"),
            "plan": plan,
            "usage": usage,
            "auth_method": conn.auth_method,
            "found_on_computer": True,
            "source": local.get("source") if local else "turnover",
        }

    if local and local.get("email"):
        return {
            "provider": "openai",
            "connected": False if is_disconnected else (local.get("source") == "turnover" and conn.connection_status == ConnectionStatus.ACCOUNT_CONNECTED),
            "email": local["email"],
            "name": local.get("name") or "ChatGPT User",
            "plan": local.get("plan") or "ChatGPT Free",
            "usage": local.get("usage"),
            "auth_method": "account",
            "found_on_computer": True,
            "source": local.get("source"),
        }
    return {"provider": "openai", "connected": False, "found_on_computer": False}


def detect_xai_account() -> dict[str, Any]:
    """Detect xAI Grok connection state."""
    conn = get_connection("xai")
    is_disconnected = (conn.connection_status == ConnectionStatus.DISCONNECTED)
    if not is_disconnected and conn.email and conn.connection_status in (ConnectionStatus.ACCOUNT_CONNECTED, ConnectionStatus.API_KEY_CONNECTED):
        return {
            "provider": "xai",
            "connected": True,
            "email": conn.email or "Grok User",
            "name": conn.account_display_name or "xAI Grok",
            "plan": "Grok Account",
            "auth_method": conn.auth_method,
            "found_on_computer": True,
        }
    return {"provider": "xai", "connected": False, "found_on_computer": False}


def detect_all_accounts() -> dict[str, dict[str, Any]]:
    """Return all detected local provider accounts."""
    return {
        "gemini": detect_google_account(),
        "claude": detect_claude_account(),
        "cursor": detect_cursor_account(),
        "openai": detect_openai_account(),
        "xai": detect_xai_account(),
    }


def connect_local_account(provider: str) -> tuple[bool, str, dict[str, Any]]:
    """Bind a detected on-computer account for the given provider to TURNOVER."""
    pid = provider.lower()
    if pid in ("anthropic", "claude"):
        info = detect_claude_account()
        if not info.get("found_on_computer") or not info.get("email"):
            return False, "No Claude account found on this computer (~/.claude.json)", {}
        conn = get_connection("claude")
        now = datetime.now(timezone.utc).isoformat()
        conn.auth_method = "account"
        conn.email = info["email"]
        conn.account_display_name = info.get("name") or "Claude User"
        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
        conn.connected_at = conn.connected_at or now
        conn.last_verified_at = now
        conn.status_message = f"Connected to {info.get('plan', 'Claude')}"
        save_connection(conn)
        return True, f"Connected {info['email']}", conn.to_dict()

    elif pid == "cursor":
        info = detect_cursor_account()
        if not info.get("found_on_computer") or not info.get("email"):
            return False, "No Cursor account found in Cursor application storage", {}
        conn = get_connection("cursor")
        now = datetime.now(timezone.utc).isoformat()
        conn.auth_method = "account"
        conn.email = info["email"]
        conn.account_display_name = info.get("name") or "Cursor User"
        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
        conn.connected_at = conn.connected_at or now
        conn.last_verified_at = now
        conn.status_message = f"Connected to {info.get('plan', 'Cursor')}"
        save_connection(conn)
        return True, f"Connected {info['email']}", conn.to_dict()

    elif pid in ("gemini", "google"):
        info = detect_google_account()
        if not info.get("connected") or not info.get("email"):
            return False, "Google OAuth token not found. Sign in with Google first.", {}
        conn = get_connection("gemini")
        now = datetime.now(timezone.utc).isoformat()
        conn.auth_method = "account"
        conn.email = info["email"]
        conn.account_display_name = "Google User"
        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
        conn.connected_at = conn.connected_at or now
        conn.last_verified_at = now
        conn.status_message = "Connected to Google Gemini"
        save_connection(conn)
        return True, f"Connected {info['email']}", conn.to_dict()

    elif pid == "openai":
        from .chatgpt_auth import adopt_local_chatgpt_session, detect_chatgpt_local_session
        info = detect_chatgpt_local_session()
        if info and info.get("email"):
            ok, msg, data = adopt_local_chatgpt_session()
            if ok:
                return True, msg, data
        conn = get_connection("openai")
        now = datetime.now(timezone.utc).isoformat()
        conn.auth_method = "account"
        if not conn.email:
            conn.email = "chatgpt-account@turnover.local"
        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
        conn.connected_at = conn.connected_at or now
        conn.last_verified_at = now
        conn.status_message = "Connected to ChatGPT Account"
        save_connection(conn)
        return True, "Connected ChatGPT account", conn.to_dict()

    elif pid in ("xai", "grok"):
        conn = get_connection("xai")
        now = datetime.now(timezone.utc).isoformat()
        conn.auth_method = "account"
        if not conn.email:
            conn.email = "grok-user@x.ai"
        conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
        conn.connected_at = conn.connected_at or now
        conn.last_verified_at = now
        conn.status_message = "Connected to xAI Grok"
        save_connection(conn)
        return True, "Connected Grok account", conn.to_dict()

    return False, f"Unknown provider {provider}", {}
