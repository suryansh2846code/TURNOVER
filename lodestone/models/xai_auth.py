"""OAuth PKCE Flow and Token Manager for xAI / Grok.

Implements the official xAI OAuth PKCE authorization flow:
- client_id: b1a00492-073a-47ea-816f-4c329264a828
- auth_url: https://auth.x.ai/oauth2/authorize
- token_url: https://auth.x.ai/oauth2/token
- redirect_port: 56121 (http://127.0.0.1:56121/callback)
- scope: openid profile email offline_access grok-cli:access api:access
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from .connections import ACCOUNT, ConnectionStatus, get_connection, save_connection

logger = logging.getLogger(__name__)

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
AUTH_BASE_URL = "https://auth.x.ai/oauth2/authorize"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
REDIRECT_PORT = 56121
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPE = "openid profile email offline_access grok-cli:access api:access"


_SECRET_KEY_XAI_TOKEN = "LODESTONE_XAI_TOKEN"


def _token_storage_path() -> Path:
    return get_settings().home / "xai_token.json"


def _load_stored_xai_data() -> dict[str, Any] | None:
    """Retrieve Lodestone-owned xAI token payload from secure Keychain store."""
    settings = get_settings()
    raw = settings.get_secret(_SECRET_KEY_XAI_TOKEN)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    # Auto-migrate legacy plaintext file to keychain if present
    legacy = settings.home / "xai_token.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text())
            settings.set_secret(_SECRET_KEY_XAI_TOKEN, json.dumps(data))
            legacy.unlink(missing_ok=True)
            return data
        except Exception:
            pass
    return None


def _save_stored_xai_data(data: dict[str, Any] | None) -> None:
    """Persist Lodestone-owned xAI token payload into secure Keychain store."""
    settings = get_settings()
    if data is None:
        settings.set_secret(_SECRET_KEY_XAI_TOKEN, None)
    else:
        settings.set_secret(_SECRET_KEY_XAI_TOKEN, json.dumps(data))
    legacy = settings.home / "xai_token.json"
    if legacy.exists():
        legacy.unlink(missing_ok=True)


def _decode_jwt_payload(jwt_token: str) -> dict[str, Any]:
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


def detect_xai_local_session() -> dict[str, Any] | None:
    """Detect existing xAI / Grok session in Lodestone secure storage."""
    data = _load_stored_xai_data()
    if data:
        try:
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
                    "name": name or "xAI User",
                    "plan": "xAI Account",
                    "has_token": bool(data.get("tokens", {}).get("access_token")),
                }
        except Exception:
            pass
    return None


def get_xai_access_token() -> str | None:
    """Retrieve active xAI access token from secure Keychain store, refreshing if expired."""
    data = _load_stored_xai_data()
    if not data:
        return None
    try:
        tokens = data.get("tokens", {})
        tok = tokens.get("access_token")
        if not tok:
            return None

        # Check expiration
        claims = _decode_jwt_payload(tok)
        exp = claims.get("exp", 0)
        if exp and time.time() > exp - 180:
            ref_tok = tokens.get("refresh_token")
            if ref_tok:
                try:
                    r = httpx.post(
                        TOKEN_URL,
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
                        _save_stored_xai_data(data)
                        return new_toks.get("access_token")
                except Exception as refresh_exc:
                    logger.warning(f"Failed to refresh xAI token: {refresh_exc}")

        return tok
    except Exception:
        return None


class _XaiAuthState:
    def __init__(self):
        self.lock = threading.Lock()
        self.server: http.server.HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.verifier: str = ""
        self.state: str = ""
        self.auth_url: str = ""
        self.status: str = "idle"  # idle | waiting | success | error
        self.error_message: str = ""
        self.connected_email: str = ""
        self.started_at: float = 0


_GLOBAL_XAI_AUTH_STATE = _XaiAuthState()


class _XaiCallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            req_path = parsed.path.rstrip("/")
            if req_path == "/cancel":
                with _GLOBAL_XAI_AUTH_STATE.lock:
                    _GLOBAL_XAI_AUTH_STATE.status = "error"
                    _GLOBAL_XAI_AUTH_STATE.error_message = "Sign-in cancelled by user"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Login cancelled")
                _stop_server_async()
                return

            if req_path != "/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            error = qs.get("error", [None])[0]
            error_desc = qs.get("error_description", [error])[0]
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

            if error:
                with _GLOBAL_XAI_AUTH_STATE.lock:
                    _GLOBAL_XAI_AUTH_STATE.status = "error"
                    _GLOBAL_XAI_AUTH_STATE.error_message = error_desc or error
                self._render_response(
                    title="TURNOVER - Grok Authorization Failed",
                    heading="✕ Authorization Failed",
                    message=error_desc or error,
                    is_error=True,
                )
                _stop_server_async()
                return

            with _GLOBAL_XAI_AUTH_STATE.lock:
                expected_state = _GLOBAL_XAI_AUTH_STATE.state
                verifier = _GLOBAL_XAI_AUTH_STATE.verifier

            if not code:
                self._render_response(
                    title="TURNOVER - Missing Code",
                    heading="✕ Missing Authorization Code",
                    message="No authorization code received from xAI.",
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

            try:
                token_resp = httpx.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": CLIENT_ID,
                        "code_verifier": verifier,
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    timeout=30.0,
                )
                if token_resp.status_code != 200:
                    raise RuntimeError(
                        f"Token exchange returned status {token_resp.status_code}: {token_resp.text[:200]}"
                    )

                token_data = token_resp.json()
                id_token = token_data.get("id_token", "")
                claims = _decode_jwt_payload(id_token) if id_token else {}
                email = claims.get("email") or token_data.get("email") or claims.get("sub") or "xAI User"
                name = claims.get("name") or "xAI Grok User"

                payload = {
                    "auth_mode": "xai_subscription",
                    "tokens": token_data,
                    "email": email,
                    "name": name,
                    "last_refresh": datetime.now(timezone.utc).isoformat(),
                }
                _save_stored_xai_data(payload)

                now = datetime.now(timezone.utc).isoformat()
                conn = get_connection("xai")
                conn.auth_method = "account"
                conn.email = email
                conn.account_display_name = name
                conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
                conn.status_message = f"Connected to Grok ({email})"
                conn.connected_at = conn.connected_at or now
                conn.last_verified_at = now
                save_connection(conn)

                try:
                    from .registry import clear_provider_cache
                    clear_provider_cache()
                except Exception:
                    pass

                with _GLOBAL_XAI_AUTH_STATE.lock:
                    _GLOBAL_XAI_AUTH_STATE.status = "success"
                    _GLOBAL_XAI_AUTH_STATE.connected_email = email

                self._render_response(
                    title="TURNOVER - Grok Authorization Successful",
                    heading="✓ Authorization Successful",
                    message=f"Your Grok account ({email}) is now connected to TURNOVER. You can close this tab and return to the app.",
                    is_error=False,
                )
            except Exception as exc:
                logger.exception("Error during xAI token exchange")
                with _GLOBAL_XAI_AUTH_STATE.lock:
                    _GLOBAL_XAI_AUTH_STATE.status = "error"
                    _GLOBAL_XAI_AUTH_STATE.error_message = str(exc)
                self._render_response(
                    title="TURNOVER - Token Exchange Failed",
                    heading="✕ Authorization Error",
                    message=f"Failed to exchange token with xAI: {exc}",
                    is_error=True,
                )

            _stop_server_async()
        except Exception as top_exc:
            logger.exception("Unhandled error in xAI OAuth callback handler")
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
      h1 {{ color: {color}; margin: 0 0 1rem 0; font-size: 1.5rem; }}
      p {{ color: #9ca3af; font-size: 0.95rem; line-height: 1.5; margin-bottom: 1.5rem; }}
      .btn {{
        display: inline-block;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.15);
        color: #f3f4f6;
        padding: 8px 16px;
        border-radius: 8px;
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
      setTimeout(() => {{ try {{ window.close(); }} catch (_) {{}} }}, 2500);
    </script>
  </body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def _stop_server_async():
    def _runner():
        time.sleep(1.0)
        with _GLOBAL_XAI_AUTH_STATE.lock:
            if _GLOBAL_XAI_AUTH_STATE.server:
                try:
                    _GLOBAL_XAI_AUTH_STATE.server.shutdown()
                    _GLOBAL_XAI_AUTH_STATE.server.server_close()
                except Exception:
                    pass
                _GLOBAL_XAI_AUTH_STATE.server = None
                _GLOBAL_XAI_AUTH_STATE.thread = None

    threading.Thread(target=_runner, daemon=True).start()


def start_xai_oauth_flow() -> tuple[bool, str, str]:
    """Start the OAuth PKCE flow on port 56121 and return the official xAI auth URL."""
    with _GLOBAL_XAI_AUTH_STATE.lock:
        if _GLOBAL_XAI_AUTH_STATE.server and (time.time() - _GLOBAL_XAI_AUTH_STATE.started_at < 180):
            return True, _GLOBAL_XAI_AUTH_STATE.auth_url, "OAuth flow already in progress"

        verifier = "".join(
            secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
            for _ in range(64)
        )
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        nonce = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")

        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
            "plan": "generic",
            "referrer": "opencode",
        }
        auth_url = f"{AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            http.server.HTTPServer.allow_reuse_address = True
            server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _XaiCallbackHandler)
        except OSError as exc:
            logger.warning(f"Could not bind to port {REDIRECT_PORT}: {exc}")
            return False, auth_url, f"Port {REDIRECT_PORT} busy: {exc}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        _GLOBAL_XAI_AUTH_STATE.server = server
        _GLOBAL_XAI_AUTH_STATE.thread = thread
        _GLOBAL_XAI_AUTH_STATE.verifier = verifier
        _GLOBAL_XAI_AUTH_STATE.state = state
        _GLOBAL_XAI_AUTH_STATE.auth_url = auth_url
        _GLOBAL_XAI_AUTH_STATE.status = "waiting"
        _GLOBAL_XAI_AUTH_STATE.started_at = time.time()
        _GLOBAL_XAI_AUTH_STATE.error_message = ""
        _GLOBAL_XAI_AUTH_STATE.connected_email = ""

        return True, auth_url, "Waiting for browser sign-in"


def disconnect() -> None:
    """Forget the stored xAI credential and stop any in-flight sign-in."""
    _save_stored_xai_data(None)
    _token_storage_path().unlink(missing_ok=True)
    _stop_server_async()


def get_xai_oauth_flow_status() -> dict[str, Any]:
    with _GLOBAL_XAI_AUTH_STATE.lock:
        return {
            "status": _GLOBAL_XAI_AUTH_STATE.status,
            "error": _GLOBAL_XAI_AUTH_STATE.error_message,
            "email": _GLOBAL_XAI_AUTH_STATE.connected_email,
            "auth_url": _GLOBAL_XAI_AUTH_STATE.auth_url,
        }
