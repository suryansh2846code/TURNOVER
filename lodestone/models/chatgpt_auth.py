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


def detect_chatgpt_local_session() -> dict[str, Any] | None:
    """Detect existing ChatGPT / Codex authentication on this machine."""
    # 1. First check Lodestone's own stored token
    our_token = _token_storage_path()
    if our_token.exists():
        try:
            data = json.loads(our_token.read_text())
            email = data.get("email")
            name = data.get("name")
            if not email and "tokens" in data:
                id_tok = data["tokens"].get("id_token", "")
                claims = _decode_jwt_payload(id_tok)
                email = claims.get("email")
                name = claims.get("name")
            if email:
                return {
                    "source": "turnover",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": "ChatGPT Subscription",
                    "has_token": bool(data.get("tokens", {}).get("access_token")),
                }
        except Exception:
            pass

    # 2. Check ~/.codex/auth.json (Codex CLI native auth)
    codex_auth = _codex_auth_path()
    if codex_auth.exists():
        try:
            data = json.loads(codex_auth.read_text())
            tokens = data.get("tokens", {})
            id_tok = tokens.get("id_token", "")
            claims = _decode_jwt_payload(id_tok)
            email = claims.get("email")
            name = claims.get("name")
            if email:
                return {
                    "source": "codex_cli",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": "ChatGPT Subscription",
                    "has_token": bool(tokens.get("access_token")),
                }
        except Exception:
            pass

    # 3. Check Turnstone / OpenCode installed session on macOS
    turnstone_auth = _turnstone_auth_path()
    if turnstone_auth.exists():
        try:
            data = json.loads(turnstone_auth.read_text())
            tokens = data.get("tokens", {})
            id_tok = tokens.get("id_token", "")
            claims = _decode_jwt_payload(id_tok)
            email = claims.get("email")
            name = claims.get("name")
            if email:
                return {
                    "source": "turnstone",
                    "email": email,
                    "name": name or "ChatGPT User",
                    "plan": "ChatGPT Subscription",
                    "has_token": bool(tokens.get("access_token")),
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
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.pathname == "/cancel":
            with _GLOBAL_AUTH_STATE.lock:
                _GLOBAL_AUTH_STATE.status = "error"
                _GLOBAL_AUTH_STATE.error_message = "Sign-in cancelled by user"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Login cancelled")
            _stop_server_async()
            return

        if parsed.pathname != "/auth/callback":
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
    """Start the OAuth flow for ChatGPT / Codex.

    Uses `codex login` CLI if installed (preferred by user), otherwise falls back
    to the built-in PKCE server on port 1455.
    """
    codex_cli = find_codex_cli()
    codex_auth = _codex_auth_path()
    initial_mtime = codex_auth.stat().st_mtime if codex_auth.exists() else 0.0

    # If official codex CLI exists, invoke `codex login`
    if codex_cli:
        try:
            proc = subprocess.Popen(
                [str(codex_cli), "login"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with _GLOBAL_AUTH_STATE.lock:
                _GLOBAL_AUTH_STATE.cli_proc = proc
                _GLOBAL_AUTH_STATE.status = "waiting"
                _GLOBAL_AUTH_STATE.started_at = time.time()
                _GLOBAL_AUTH_STATE.error_message = ""
                _GLOBAL_AUTH_STATE.connected_email = ""

            _watch_codex_auth_file_async(initial_mtime)

            # Build direct fallback URL with valid PKCE params in case user needs to open manually
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
            return True, auth_url, "Launched Codex CLI sign-in in browser"
        except Exception as exc:
            logger.warning(f"Could not launch codex CLI: {exc}, falling back to built-in server")

    # Built-in PKCE fallback server
    with _GLOBAL_AUTH_STATE.lock:
        if _GLOBAL_AUTH_STATE.server and (time.time() - _GLOBAL_AUTH_STATE.started_at < 180):
            return True, _GLOBAL_AUTH_STATE.auth_url, "OAuth flow already in progress"

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
