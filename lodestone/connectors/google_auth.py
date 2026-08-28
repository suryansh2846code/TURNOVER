"""Shared Google OAuth (Desktop flow) for Gmail + Drive connectors.

Tokens are cached under LODESTONE_HOME so the browser consent only happens once.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import get_settings

# Read-only scopes — Lodestone never modifies your Google data.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _token_path() -> Path:
    return get_settings().home / "google_token.json"


def get_credentials(interactive: bool = True):
    """Return valid Google credentials, running the consent flow if needed."""
    from google.auth.transport.requests import Request  # lazy
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = get_settings()
    token_path = _token_path()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds

    if not interactive:
        raise RuntimeError("Google auth required; run an interactive sync once.")

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


def google_ready() -> tuple[bool, str]:
    settings = get_settings()
    if _token_path().exists():
        return True, ""
    if settings.google_client_secrets and Path(settings.google_client_secrets).exists():
        return True, "will prompt for consent on first sync"
    return False, "no Google OAuth client secrets configured"
