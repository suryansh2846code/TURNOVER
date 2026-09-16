"""Reading the xAI credential a previous Chitragupta version stored.

**This module no longer performs a sign-in, and holds no OAuth client.** It
used to run an OAuth PKCE flow against `auth.x.ai` using client id
`b1a00492-…` with `referrer=opencode` — neither of which belong to Chitragupta.
They were OpenCode's, and sending them told xAI that a different product was
making the request. Borrowing another project's client identity is not ours to
do, and it makes every Chitragupta user's sign-in breakable by a vendor decision
aimed at somebody else.

The flow was also already unreachable: an xAI OAuth token authenticates but
grants no `api.x.ai` credits (402 `personal-team-blocked:spending-limit`), so
`auth_flows.py` routes xAI sign-in through `GrokFlow` and the vendor's own
Grok Build CLI instead — the same sanctioned shape as the Claude and Cursor
backends, where the CLI owns the OAuth client because it is the vendor's.

What remains is the read side, kept because a user who signed in under the old
build still has a token in their Keychain: detect it, decode it, hand it to
`XAIProvider` so it can explain the subscription/credits split, and forget it on
disconnect. It is deliberately **not** refreshed — refreshing needs the client
id, and that is exactly what we will not send.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..log import get_logger, suppressed

log = get_logger(__name__)



_SECRET_KEY_XAI_TOKEN = "CHITRAGUPTA_XAI_TOKEN"


def _token_storage_path() -> Path:
    return get_settings().home / "xai_token.json"


def _load_stored_xai_data() -> dict[str, Any] | None:
    """Retrieve Chitragupta-owned xAI token payload from secure Keychain store."""
    settings = get_settings()
    raw = settings.get_secret(_SECRET_KEY_XAI_TOKEN)
    if raw:
        with suppressed("return json.loads(raw)"):
            return json.loads(raw)
    # Auto-migrate legacy plaintext file to keychain if present
    legacy = settings.home / "xai_token.json"
    if legacy.exists():
        with suppressed("data = json.loads(legacy.read_text()) …"):
            data = json.loads(legacy.read_text())
            settings.set_secret(_SECRET_KEY_XAI_TOKEN, json.dumps(data))
            legacy.unlink(missing_ok=True)
            return data
    return None


def _save_stored_xai_data(data: dict[str, Any] | None) -> None:
    """Persist Chitragupta-owned xAI token payload into secure Keychain store."""
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
        log.warning("Failed to parse JWT payload: %s", exc)
        return {}


def detect_xai_local_session() -> dict[str, Any] | None:
    """Detect existing xAI / Grok session in Chitragupta secure storage."""
    data = _load_stored_xai_data()
    if data:
        with suppressed("email = data.get('email') …"):
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

        # An expired token is simply gone. Refreshing it means posting the
        # OAuth client id to xAI, and the only client id this flow ever had was
        # another project's — so a stale credential is dropped and the user is
        # sent to the supported path (the Grok CLI) instead of being silently
        # authenticated as someone else's app.
        claims = _decode_jwt_payload(tok)
        exp = claims.get("exp", 0)
        if exp and time.time() > exp - 180:
            log.info("stored xAI token has expired; sign in again via the Grok CLI")
            return None

        return tok
    except Exception:
        return None


def disconnect() -> None:
    """Forget the stored xAI credential."""
    _save_stored_xai_data(None)
    _token_storage_path().unlink(missing_ok=True)
