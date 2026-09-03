"""Shared Google OAuth (Desktop flow) for Gmail + Drive connectors.

Tokens are cached under LODESTONE_HOME so the browser consent only happens once.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import get_settings

# Read scopes + narrow WRITE scopes for confirmed actions (send email, create
# event). Reading never modifies data; writes only run after explicit user
# confirmation. gmail.send can only send, not read/delete.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _token_path() -> Path:
    return get_settings().home / "google_token.json"


def get_credentials(interactive: bool = True):
    """Return valid Google credentials, running the consent flow if needed.

    Self-healing: a corrupt token file, or a refresh token that has been
    revoked/expired (e.g. the 7-day expiry of Google 'Testing'-mode apps), is
    dropped and re-consented instead of failing every sync forever."""
    from google.auth.exceptions import RefreshError  # lazy
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = get_settings()
    token_path = _token_path()
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            token_path.unlink(missing_ok=True)     # corrupt token → re-consent
            creds = None

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
            return creds
        except RefreshError:
            # refresh token revoked/expired → drop it and fall through to consent
            token_path.unlink(missing_ok=True)
            creds = None

    if not interactive:
        raise RuntimeError(
            "Google sign-in expired or missing. Open Lodestone and reconnect "
            "Google (Connectors → Sign in with Google) to re-authorize.")

    secrets = settings.google_client_secrets
    if not secrets or not Path(secrets).exists():
        raise RuntimeError(
            "Missing Google OAuth client secrets. Create a Desktop OAuth client in "
            "Google Cloud Console and set GOOGLE_CLIENT_SECRETS to its JSON path "
            f"(or drop it at {settings.home / 'google_client_secret.json'})."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    return creds


_SCOPE_SERVICES = [("gmail", "Gmail"), ("drive", "Drive"), ("calendar", "Calendar")]


def granted_services() -> list[str]:
    """Friendly names of the services the stored token is authorized for."""
    if not _token_path().exists():
        return []
    try:
        scopes = json.loads(_token_path().read_text()).get("scopes", [])
    except Exception:
        return []
    return [label for key, label in _SCOPE_SERVICES
            if any(key in s for s in scopes)]


def _account_path() -> Path:
    return get_settings().home / "google_account.json"


def connected_email(fetch: bool = True) -> str | None:
    """The signed-in Google address. Cached locally; fetched once via Gmail
    getProfile when connected (no extra scope needed)."""
    ap = _account_path()
    if ap.exists():
        try:
            return json.loads(ap.read_text()).get("email")
        except Exception:
            pass
    if not fetch or not _token_path().exists():
        return None
    try:
        from googleapiclient.discovery import build
        creds = get_credentials(interactive=False)
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        email = svc.users().getProfile(userId="me").execute().get("emailAddress")
        if email:
            ap.write_text(json.dumps({"email": email}))
        return email
    except Exception:
        return None


def disconnect() -> None:
    """Sign out of Google: remove the local token + cached account."""
    for p in (_token_path(), _account_path()):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def google_ready() -> tuple[bool, str]:
    settings = get_settings()
    if _token_path().exists():
        return True, ""
    if settings.google_client_secrets and Path(settings.google_client_secrets).exists():
        return True, "will prompt for consent on first sync"
    return False, "no Google OAuth client secrets configured"
