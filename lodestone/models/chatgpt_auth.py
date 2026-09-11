"""OAuth PKCE Flow and Token Manager for ChatGPT / OpenAI Codex.

Implements the official OpenAI OAuth PKCE authorization flow for ChatGPT subscriptions,
compatible with the Codex client (`app_EMoamEEZ73f0CkXaXp7hrann`):
1. Integrates natively with the `codex` CLI (`codex login`) or built-in loopback server on port 1455.
2. Opens the official OpenAI authorization consent page (Choose an account to continue to Codex).
3. Exchanges authorization code for tokens (access_token, refresh_token, id_token).
4. Decodes user identity (email, display name) and safely stores tokens in Lodestone and ~/.codex.
5. Updates provider connection state for immediate live reflection in TURNOVER.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from .connections import ConnectionStatus, get_connection, save_connection

logger = logging.getLogger(__name__)

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE_URL = "https://auth.openai.com"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
SCOPE = "openid profile email offline_access"


def _token_storage_path() -> Path:
    return get_settings().home / "chatgpt_token.json"


def _codex_auth_path() -> Path:
    return Path.home() / ".codex/auth.json"


def _turnstone_auth_path() -> Path:
    return Path.home() / "Library/Application Support/Turnstone/provider-auth/codex/auth.json"


def find_codex_cli() -> Path | None:
    """Locate the official Codex CLI binary on this machine."""
    which_p = shutil.which("codex")
    if which_p:
        return Path(which_p)

    candidates = [
        Path.home() / "Library/Application Support/Turnstone/bin/codex",
        Path.home() / ".local/bin/codex",
        Path("/opt/homebrew/bin/codex"),
        Path("/usr/local/bin/codex"),
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return None


def _decode_jwt_payload(jwt_token: str) -> dict[str, Any]:
    """Decode unverified JWT payload for identity extraction without third-party libs."""
    if not jwt_token or "." not in jwt_token:
        return {}
    try:
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        data = base64.urlsafe_b64decode(payload.encode("utf-8"))
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to parse JWT payload: {exc}")
        return {}


_CHATGPT_PLAN_LABELS: dict[str, str] = {
    "free": "ChatGPT Free",
    "go": "ChatGPT Go",
    "plus": "ChatGPT Plus",
    "pro": "ChatGPT Pro",
    "prolite": "ChatGPT Pro",
    "team": "ChatGPT Team",
    "self_serve_business_usage_based": "ChatGPT Business",
    "business": "ChatGPT Business",
    "enterprise_cbp_usage_based": "ChatGPT Enterprise",
    "enterprise": "ChatGPT Enterprise",
    "edu": "ChatGPT Education",
}

_USAGE_CACHE: dict[str, Any] = {}
_USAGE_CACHE_TIME: float = 0.0
_USAGE_CACHE_TTL: float = 30.0


def _format_chatgpt_plan(raw_plan: str | None) -> str:
    if not raw_plan:
        return "ChatGPT Free"
    clean = str(raw_plan).strip().lower()
    return _CHATGPT_PLAN_LABELS.get(clean, f"ChatGPT {clean.title()}")


def _extract_plan_and_account_from_tokens(data: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """Extract (plan_name, email, display_name, account_id) from stored tokens/claims."""
    tokens = data.get("tokens") or {}
    access_tok = tokens.get("access_token") or ""
    id_tok = tokens.get("id_token") or ""

    claims = _decode_jwt_payload(access_tok) or {}
    id_claims = _decode_jwt_payload(id_tok) or {}

    auth_info = claims.get("https://api.openai.com/auth") or id_claims.get("https://api.openai.com/auth") or {}
    raw_plan = auth_info.get("chatgpt_plan_type") or data.get("plan_type")
    account_id = auth_info.get("chatgpt_account_id") or tokens.get("account_id")

    profile_info = claims.get("https://api.openai.com/profile") or id_claims.get("https://api.openai.com/profile") or {}
    email = data.get("email") or profile_info.get("email") or claims.get("email") or id_claims.get("email") or ""
    name = data.get("name") or profile_info.get("name") or claims.get("name") or id_claims.get("name") or ""

    plan_name = _format_chatgpt_plan(raw_plan)
    return plan_name, email, name, account_id


def clear_chatgpt_usage_cache() -> None:
    global _USAGE_CACHE, _USAGE_CACHE_TIME
    _USAGE_CACHE = {}
    _USAGE_CACHE_TIME = 0.0


def get_chatgpt_subscription_usage(force_refresh: bool = False) -> dict[str, Any] | None:
    """Fetch live usage limits and rate limit windows from ChatGPT backend."""
    global _USAGE_CACHE, _USAGE_CACHE_TIME
    now = time.time()
    if not force_refresh and _USAGE_CACHE and (now - _USAGE_CACHE_TIME < _USAGE_CACHE_TTL):
        return _USAGE_CACHE

    token = get_chatgpt_access_token()
    if not token:
        turnstone_f = _turnstone_auth_path()
        if turnstone_f.exists():
            try:
                td = json.loads(turnstone_f.read_text())
                token = td.get("tokens", {}).get("access_token")
            except Exception:
                pass
    if not token:
        return None

    account_id = None
    plan_from_jwt = "free"
    try:
        claims = _decode_jwt_payload(token)
        auth_claims = claims.get("https://api.openai.com/auth") or {}
        account_id = auth_claims.get("chatgpt_account_id")
        plan_from_jwt = auth_claims.get("chatgpt_plan_type") or "free"
    except Exception:
        pass

    try:
        import urllib.request
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "codex_cli_rs/0.153.4",
            "Accept": "application/json",
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        req = urllib.request.Request("https://chatgpt.com/backend-api/wham/usage", headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                rate_limit = body.get("rate_limit") or {}
                primary = rate_limit.get("primary_window") or {}
                windows = []
                if primary:
                    duration_secs = primary.get("limit_window_seconds")
                    duration_mins = (duration_secs // 60) if duration_secs else None
                    if duration_mins is None:
                        label = "Primary limit"
                    elif duration_mins == 10080:
                        label = "Weekly limit"
                    elif duration_mins == 1440:
                        label = "Daily limit"
                    elif duration_mins % 1440 == 0:
                        label = f"{duration_mins // 1440}-day limit"
                    elif duration_mins % 60 == 0:
                        label = f"{duration_mins // 60}-hour limit"
                    else:
                        label = f"{duration_mins}-minute limit"

                    reset_at = primary.get("reset_at")
                    resets_at_ms = int(reset_at * 1000) if reset_at else None
                    windows.append({
                        "id": "primary",
                        "label": label,
                        "usedPercent": primary.get("used_percent", 0),
                        "resetsAt": resets_at_ms,
                    })

                usage_res = {
                    "state": "available",
                    "updatedAt": int(time.time() * 1000),
                    "windows": windows,
                    "plan": _format_chatgpt_plan(body.get("plan_type") or plan_from_jwt),
                    "planType": body.get("plan_type") or plan_from_jwt,
                }
                _USAGE_CACHE = usage_res
                _USAGE_CACHE_TIME = time.time()
                return usage_res
    except Exception as exc:
        logger.warning(f"ChatGPT live usage query failed: {exc}")

    if _USAGE_CACHE:
        return _USAGE_CACHE
    return None


def detect_chatgpt_local_session(fetch_usage: bool = True) -> dict[str, Any] | None:
    """Detect existing ChatGPT / Codex authentication on this machine."""
    # 1. First check Lodestone's own stored token
    our_token = _token_storage_path()
    if our_token.exists():
        try:
            data = json.loads(our_token.read_text())
            plan_name, email, name, account_id = _extract_plan_and_account_from_tokens(data)
            if email:
                usage = get_chatgpt_subscription_usage() if fetch_usage else None
                if usage and usage.get("plan"):
                    plan_name = usage["plan"]
                return {
                    "source": "turnover",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": plan_name,
                    "usage": usage,
                    "has_token": bool(data.get("tokens", {}).get("access_token")),
                }
        except Exception:
            pass

    # 2. Check ~/.codex/auth.json (Codex CLI native auth)
    codex_auth = _codex_auth_path()
    if codex_auth.exists():
        try:
            data = json.loads(codex_auth.read_text())
            plan_name, email, name, account_id = _extract_plan_and_account_from_tokens(data)
            if email:
                usage = get_chatgpt_subscription_usage() if fetch_usage else None
                if usage and usage.get("plan"):
                    plan_name = usage["plan"]
                return {
                    "source": "codex_cli",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": plan_name,
                    "usage": usage,
                    "has_token": bool(data.get("tokens", {}).get("access_token")),
                }
        except Exception:
            pass

    # 3. Check Turnstone / OpenCode installed session on macOS
    turnstone_auth = _turnstone_auth_path()
    if turnstone_auth.exists():
        try:
            data = json.loads(turnstone_auth.read_text())
            plan_name, email, name, account_id = _extract_plan_and_account_from_tokens(data)
            if email:
                usage = get_chatgpt_subscription_usage() if fetch_usage else None
                if usage and usage.get("plan"):
                    plan_name = usage["plan"]
                return {
                    "source": "turnstone",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": plan_name,
                    "usage": usage,
                    "has_token": bool(data.get("tokens", {}).get("access_token")),
                }
        except Exception:
            pass

    return None


def adopt_local_chatgpt_session() -> tuple[bool, str, dict[str, Any]]:
    """Adopt credentials found in Codex CLI, Turnstone or local storage into TURNOVER."""
    info = detect_chatgpt_local_session()
    if not info or not info.get("email"):
        return False, "No local ChatGPT session found on this computer", {}

    # Copy tokens over safely to Lodestone storage
    source = info.get("source")
    src_file = _codex_auth_path() if source == "codex_cli" else _turnstone_auth_path() if source == "turnstone" else None
    if src_file and src_file.exists():
        try:
            src_data = json.loads(src_file.read_text())
            _token_storage_path().parent.mkdir(parents=True, exist_ok=True)
            _token_storage_path().write_text(json.dumps(src_data, indent=2))
        except Exception as exc:
            logger.warning(f"Could not copy {source} session: {exc}")

    # Mark connection as active in DB
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection("openai")
    conn.auth_method = "account"
    conn.email = info["email"]
    conn.account_display_name = info.get("name") or "ChatGPT User"
    conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
    conn.status_message = f"Connected to ChatGPT ({info['email']})"
    conn.connected_at = conn.connected_at or now
    conn.last_verified_at = now
    save_connection(conn)

    return True, f"Connected {info['email']}", conn.to_dict()


class _AuthServerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.server: http.server.HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.cli_proc: subprocess.Popen | None = None
        self.verifier: str = ""
        self.state: str = ""
        self.auth_url: str = ""
        self.status: str = "idle"  # idle | waiting | success | error
        self.error_message: str = ""
        self.connected_email: str = ""
        self.started_at: float = 0


_GLOBAL_AUTH_STATE = _AuthServerState()


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            req_path = parsed.path.rstrip("/")
            if req_path == "/cancel":
                with _GLOBAL_AUTH_STATE.lock:
                    _GLOBAL_AUTH_STATE.status = "error"
                    _GLOBAL_AUTH_STATE.error_message = "Sign-in cancelled by user"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Login cancelled")
                _stop_server_async()
                return

            if req_path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            error = qs.get("error", [None])[0]
            error_desc = qs.get("error_description", [error])[0]
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

            if error:
                with _GLOBAL_AUTH_STATE.lock:
                    _GLOBAL_AUTH_STATE.status = "error"
                    _GLOBAL_AUTH_STATE.error_message = error_desc or error
                self._render_response(
                    title="TURNOVER - Authorization Failed",
                    heading="✕ Authorization Failed",
                    message=error_desc or error,
                    is_error=True,
                )
                _stop_server_async()
                return

            with _GLOBAL_AUTH_STATE.lock:
                expected_state = _GLOBAL_AUTH_STATE.state
                verifier = _GLOBAL_AUTH_STATE.verifier

            if not code:
                self._render_response(
                    title="TURNOVER - Missing Code",
                    heading="✕ Missing Authorization Code",
                    message="No authorization code received from OpenAI.",
                    is_error=True,
                )
                _stop_server_async()
                return

            if expected_state and state != expected_state:
                self._render_response(
                    title="TURNOVER - Invalid State",
                    heading="✕ Security Verification Failed",
                    message="OAuth state mismatch. Please try again.",
                    is_error=True,
                )
                _stop_server_async()
                return

            # Perform token exchange
            try:
                token_resp = httpx.post(
                    f"{AUTH_BASE_URL}/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": CLIENT_ID,
                        "code_verifier": verifier,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )
                if token_resp.status_code != 200:
                    raise RuntimeError(
                        f"Token exchange returned status {token_resp.status_code}: {token_resp.text[:200]}"
                    )

                token_data = token_resp.json()
                id_token = token_data.get("id_token", "")
                claims = _decode_jwt_payload(id_token)
                email = claims.get("email") or "ChatGPT User"
                name = claims.get("name") or "ChatGPT Account"

                # Persist tokens securely
                storage_file = _token_storage_path()
                storage_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "auth_mode": "chatgpt_subscription",
                    "tokens": token_data,
                    "email": email,
                    "name": name,
                    "last_refresh": datetime.now(timezone.utc).isoformat(),
                }
                storage_file.write_text(json.dumps(payload, indent=2))

                # Update DB connection record
                now = datetime.now(timezone.utc).isoformat()
                conn = get_connection("openai")
                conn.auth_method = "account"
                conn.email = email
                conn.account_display_name = name
                conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
                conn.status_message = f"Connected to ChatGPT ({email})"
                conn.connected_at = conn.connected_at or now
                conn.last_verified_at = now
                save_connection(conn)

                try:
                    from .registry import clear_provider_cache
                    clear_provider_cache()
                except Exception:
                    pass

                with _GLOBAL_AUTH_STATE.lock:
                    _GLOBAL_AUTH_STATE.status = "success"
                    _GLOBAL_AUTH_STATE.connected_email = email

                self._render_response(
                    title="TURNOVER - Authorization Successful",
                    heading="✓ Authorization Successful",
                    message=f"Your ChatGPT account ({email}) is now connected to TURNOVER. You can close this tab and return to the app.",
                    is_error=False,
                )
            except Exception as exc:
                logger.exception("Error during ChatGPT token exchange")
                with _GLOBAL_AUTH_STATE.lock:
                    _GLOBAL_AUTH_STATE.status = "error"
                    _GLOBAL_AUTH_STATE.error_message = str(exc)
                self._render_response(
                    title="TURNOVER - Token Exchange Failed",
                    heading="✕ Authorization Error",
                    message=f"Failed to exchange token with OpenAI: {exc}",
                    is_error=True,
                )

            _stop_server_async()
        except Exception as top_exc:
            logger.exception("Unhandled error in ChatGPT OAuth callback handler")
            try:
                self._render_response(
                    title="TURNOVER - Error",
                    heading="✕ Sign-In Processing Error",
                    message=str(top_exc),
                    is_error=True,
                )
            except Exception:
                pass
            _stop_server_async()

    def _render_response(self, title: str, heading: str, message: str, is_error: bool = False):
        color = "#fc533a" if is_error else "#10b981"
        bg = "#111827"
        card_bg = "#1f2937"
        html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        margin: 0;
        background: {bg};
        color: #f3f4f6;
      }}
      .container {{
        text-align: center;
        padding: 2.5rem;
        background: {card_bg};
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        max-width: 440px;
      }}
      h1 {{
        color: {color};
        margin: 0 0 1rem 0;
        font-size: 1.5rem;
      }}
      p {{
        color: #9ca3af;
        font-size: 0.95rem;
        line-height: 1.5;
        margin-bottom: 1.5rem;
      }}
      .btn {{
        display: inline-block;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.15);
        color: #f3f4f6;
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 0.9rem;
        text-decoration: none;
        cursor: pointer;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <h1>{heading}</h1>
      <p>{message}</p>
      <button class="btn" onclick="window.close()">Close Window</button>
    </div>
    <script>
      setTimeout(() => {{
        try {{ window.close(); }} catch (_) {{}}
      }}, 2500);
    </script>
  </body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def _stop_server_async():
    def _runner():
        time.sleep(1.0)
        with _GLOBAL_AUTH_STATE.lock:
            if _GLOBAL_AUTH_STATE.server:
                try:
                    _GLOBAL_AUTH_STATE.server.shutdown()
                    _GLOBAL_AUTH_STATE.server.server_close()
                except Exception:
                    pass
                _GLOBAL_AUTH_STATE.server = None
                _GLOBAL_AUTH_STATE.thread = None

    threading.Thread(target=_runner, daemon=True).start()


def _watch_codex_auth_file_async(initial_mtime: float):
    """Background watcher that detects when Codex CLI writes auth.json after login."""
    def _watcher():
        auth_file = _codex_auth_path()
        for _ in range(150):  # watch for up to 3 minutes
            time.sleep(1.2)
            if not auth_file.exists():
                continue
            try:
                mtime = auth_file.stat().st_mtime
                if mtime > initial_mtime:
                    # File was updated!
                    data = json.loads(auth_file.read_text())
                    tokens = data.get("tokens", {})
                    id_tok = tokens.get("id_token", "")
                    claims = _decode_jwt_payload(id_tok)
                    email = claims.get("email")
                    name = claims.get("name")
                    if email and tokens.get("access_token"):
                        # Adopt session
                        adopt_local_chatgpt_session()
                        with _GLOBAL_AUTH_STATE.lock:
                            _GLOBAL_AUTH_STATE.status = "success"
                            _GLOBAL_AUTH_STATE.connected_email = email
                        logger.info(f"Codex CLI authenticated successfully as {email}")
                        break
            except Exception as exc:
                logger.debug(f"Watching auth.json: {exc}")

    t = threading.Thread(target=_watcher, daemon=True)
    t.start()


def start_chatgpt_oauth_flow() -> tuple[bool, str, str]:
    """Start the native OAuth PKCE loopback flow for ChatGPT / OpenAI on port 1455."""
    with _GLOBAL_AUTH_STATE.lock:
        # Kill previous CLI process if any
        if _GLOBAL_AUTH_STATE.cli_proc:
            try:
                _GLOBAL_AUTH_STATE.cli_proc.terminate()
            except Exception:
                pass
            _GLOBAL_AUTH_STATE.cli_proc = None

        # Cleanly stop any existing server before starting a fresh one
        if _GLOBAL_AUTH_STATE.server:
            try:
                _GLOBAL_AUTH_STATE.server.shutdown()
                _GLOBAL_AUTH_STATE.server.server_close()
            except Exception:
                pass
            _GLOBAL_AUTH_STATE.server = None
            _GLOBAL_AUTH_STATE.thread = None

        verifier = "".join(
            secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
            for _ in range(43)
        )
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        state = secrets.token_hex(16)

        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "opencode",
        }
        auth_url = f"{AUTH_BASE_URL}/oauth/authorize?{urllib.parse.urlencode(params)}"

        try:
            http.server.HTTPServer.allow_reuse_address = True
            server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _OAuthCallbackHandler)
        except OSError as exc:
            logger.warning(f"Could not bind to port {REDIRECT_PORT}: {exc}")
            return False, auth_url, f"Port {REDIRECT_PORT} busy: {exc}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        _GLOBAL_AUTH_STATE.server = server
        _GLOBAL_AUTH_STATE.thread = thread
        _GLOBAL_AUTH_STATE.verifier = verifier
        _GLOBAL_AUTH_STATE.state = state
        _GLOBAL_AUTH_STATE.auth_url = auth_url
        _GLOBAL_AUTH_STATE.status = "waiting"
        _GLOBAL_AUTH_STATE.started_at = time.time()
        _GLOBAL_AUTH_STATE.error_message = ""
        _GLOBAL_AUTH_STATE.connected_email = ""

        return True, auth_url, "Waiting for browser sign-in"


def get_oauth_flow_status() -> dict[str, Any]:
    """Check current status of ongoing OAuth sign-in."""
    with _GLOBAL_AUTH_STATE.lock:
        return {
            "status": _GLOBAL_AUTH_STATE.status,
            "error": _GLOBAL_AUTH_STATE.error_message,
            "email": _GLOBAL_AUTH_STATE.connected_email,
            "auth_url": _GLOBAL_AUTH_STATE.auth_url,
        }


def get_chatgpt_access_token() -> str | None:
    """Retrieve active ChatGPT access token, refreshing it automatically if expired."""
    for p in [_token_storage_path(), _turnstone_auth_path(), _codex_auth_path()]:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
            tokens = data.get("tokens", {})
            tok = tokens.get("access_token")
            if not tok:
                continue

            # Check expiration
            claims = _decode_jwt_payload(tok)
            exp = claims.get("exp", 0)
            if exp and time.time() > exp - 180:
                ref_tok = tokens.get("refresh_token")
                if ref_tok:
                    try:
                        r = httpx.post(
                            f"{AUTH_BASE_URL}/oauth/token",
                            data={
                                "grant_type": "refresh_token",
                                "refresh_token": ref_tok,
                                "client_id": CLIENT_ID,
                            },
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                            timeout=15.0,
                        )
                        if r.status_code == 200:
                            new_toks = r.json()
                            data["tokens"] = new_toks
                            data["last_refresh"] = datetime.now(timezone.utc).isoformat()
                            _token_storage_path().write_text(json.dumps(data, indent=2))
                            return new_toks.get("access_token")
                    except Exception as refresh_exc:
                        logger.warning(f"Failed to refresh ChatGPT token: {refresh_exc}")

            return tok
        except Exception:
            pass

    return None


def chat_with_chatgpt_subscription(
    messages: list[Any],
    *,
    model: str | None = None,
    tools: list[Any] | None = None,
    timeout: float = 120.0,
) -> Any:
    """Execute a chat completion request through ChatGPT Subscription backend."""
    import uuid
    from .base import ChatResult, ToolCall

    token = get_chatgpt_access_token()
    if not token:
        return ChatResult(text="⚠️ ChatGPT account not connected or session expired. Please Sign in with ChatGPT in Models.")

    input_items = []
    for m in messages:
        if m.role in ("user", "system"):
            input_items.append({"role": m.role, "content": m.content})
        elif m.role == "assistant":
            if m.content:
                input_items.append({"role": "assistant", "content": m.content})
            for tc in m.tool_calls:
                args_str = json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments or "{}")
                input_items.append({
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": args_str,
                })
        elif m.role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": m.tool_call_id or "",
                "output": m.content or "",
            })

    tools_payload = []
    if tools:
        for t in tools:
            tools_payload.append({
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })

    # 1. Determine models supported by the current user session / plan
    supported_models: set[str] = set()
    models_cache_candidates = [
        _turnstone_auth_path().parent / "models_cache.json",
        Path.home() / ".codex/models_cache.json",
        Path.home() / ".lodestone/models_cache.json",
    ]
    for cache_p in models_cache_candidates:
        if cache_p.exists():
            try:
                cdata = json.loads(cache_p.read_text())
                supported_models = {m.get("slug") for m in cdata.get("models", []) if m.get("slug")}
                if supported_models:
                    break
            except Exception:
                pass

    local_sess = detect_chatgpt_local_session(fetch_usage=False)
    user_plan = (local_sess and local_sess.get("plan")) or "ChatGPT Free"

    if not supported_models:
        if "free" in user_plan.lower():
            supported_models = {"gpt-5.6-terra", "gpt-5.6-luna", "gpt-reserve", "gpt-5.5", "codex-auto-review"}
        elif "plus" in user_plan.lower():
            supported_models = {"gpt-5.6-terra", "gpt-5.6-luna", "gpt-reserve", "gpt-5.5", "o3-mini", "codex-auto-review"}
        else:
            supported_models = {"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-reserve", "gpt-5.5", "o3-mini", "codex-auto-review"}

    from .entitlements import evaluate_model_entitlement, get_best_unlocked_model

    # 2. Select and validate model
    req_model = (model or "").strip()
    if not req_model or req_model.lower() in ("auto", "default"):
        # Auto-pick best available model supported by user's plan
        chosen_model = get_best_unlocked_model(
            provider="openai",
            available_models=list(supported_models) if supported_models else ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"],
            is_connected=True,
            user_plan=user_plan,
        ) or "gpt-5.6-terra"
    else:
        locked, plan_req = evaluate_model_entitlement("openai", req_model, is_connected=True, user_plan=user_plan)
        if locked or (supported_models and req_model not in supported_models):
            req_plan = plan_req or "Pro"
            display_avail = [m for m in sorted(supported_models) if not m.startswith("codex-auto")] if supported_models else ["gpt-5.6-terra", "gpt-5.6-luna"]
            avail_str = ", ".join(f"`{m}`" for m in display_avail)
            return ChatResult(
                text=f"🔒 Model `{req_model}` is not supported on your **{user_plan}** plan (requires **{req_plan}**).\n\n"
                     f"Available models on your plan: {avail_str}.\n\n"
                     f"Please select an available model in the model selector."
            )
        chosen_model = req_model

    payload = {
        "model": chosen_model,
        "store": False,
        "stream": True,
        "input": input_items,
    }
    if tools_payload:
        payload["tools"] = tools_payload

    full_text = ""
    calls = []
    try:
        with httpx.stream(
            "POST",
            "https://chatgpt.com/backend-api/codex/responses",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    evt = json.loads(data_str)
                    etype = evt.get("type")
                    if etype == "response.output_text.delta":
                        full_text += evt.get("delta", "")
                    elif etype == "response.output_item.done":
                        item = evt.get("item", {})
                        if item.get("type") == "function_call":
                            cid = item.get("call_id") or item.get("id") or str(uuid.uuid4())
                            cname = item.get("name", "")
                            cargs = item.get("arguments", "{}")
                            try:
                                parsed_args = json.loads(cargs)
                            except Exception:
                                parsed_args = {}
                            calls.append(ToolCall(id=cid, name=cname, arguments=parsed_args))
                except Exception:
                    pass
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            return ChatResult(text="⚠️ ChatGPT subscription session expired or invalid. Please sign in again in Models.")
        elif code == 429:
            return ChatResult(text="⚠️ ChatGPT rate limited. Please wait a moment and retry.")
        return ChatResult(text=f"⚠️ ChatGPT subscription error ({code}): {exc.response.text[:150]}")
    except Exception as exc:
        return ChatResult(text=f"⚠️ Error connecting to ChatGPT subscription: {exc}")

    return ChatResult(text=full_text, tool_calls=calls)
