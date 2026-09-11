"""Provider connection state management for TURNOVER / Lodestone.

Tracks connected accounts, authentication methods, identity metadata (email,
account display name), connection statuses, verification timestamps, and scopes.
Raw credentials and secrets are NEVER stored in this record or database.
Credentials are kept exclusively in the system keychain / encrypted secrets store.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings


class ConnectionStatus:
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ACCOUNT_CONNECTED = "ACCOUNT_CONNECTED"
    API_KEY_CONNECTED = "API_KEY_CONNECTED"
    ACCOUNT_FOUND_ON_COMPUTER = "ACCOUNT_FOUND_ON_COMPUTER"
    REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    PROVIDER_VERIFICATION_REQUIRED = "PROVIDER_VERIFICATION_REQUIRED"
    MODEL_ACCESS_UNAVAILABLE = "MODEL_ACCESS_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


@dataclass
class ProviderConnection:
    provider: str
    auth_method: str = "api_key"          # "account" | "api_key" | "cli" | "local"
    account_id: str | None = None
    account_display_name: str | None = None
    email: str | None = None
    connection_status: str = ConnectionStatus.NOT_CONNECTED
    connected_at: str | None = None
    last_verified_at: str | None = None
    credential_reference: str | None = None  # e.g. "OPENAI_API_KEY", never the secret itself
    expires_at: str | None = None
    scopes: list[str] = field(default_factory=list)
    status_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scopes"] = list(self.scopes)
        return d


_SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_connections (
    provider               TEXT PRIMARY KEY,
    auth_method            TEXT NOT NULL,
    account_id             TEXT,
    account_display_name   TEXT,
    email                  TEXT,
    connection_status      TEXT NOT NULL,
    connected_at           TEXT,
    last_verified_at       TEXT,
    credential_reference   TEXT,
    expires_at             TEXT,
    scopes                 TEXT,
    status_message         TEXT
);
"""


def _get_db() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def get_connection(provider: str) -> ProviderConnection:
    """Retrieve persisted connection metadata for a provider."""
    pid = provider.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM provider_connections WHERE provider = ?",
        (pid,),
    ).fetchone()

    if row:
        scopes = []
        if row["scopes"]:
            try:
                scopes = json.loads(row["scopes"])
            except Exception:
                scopes = []
        return ProviderConnection(
            provider=row["provider"],
            auth_method=row["auth_method"],
            account_id=row["account_id"],
            account_display_name=row["account_display_name"],
            email=row["email"],
            connection_status=row["connection_status"],
            connected_at=row["connected_at"],
            last_verified_at=row["last_verified_at"],
            credential_reference=row["credential_reference"],
            expires_at=row["expires_at"],
            scopes=scopes,
            status_message=row["status_message"] or "",
        )

    return ProviderConnection(provider=pid)


def save_connection(conn_data: ProviderConnection) -> None:
    """Save or update provider connection state."""
    db = _get_db()
    pid = conn_data.provider.lower()
    scopes_json = json.dumps(conn_data.scopes or [])

    db.execute(
        """
        INSERT INTO provider_connections (
            provider, auth_method, account_id, account_display_name, email,
            connection_status, connected_at, last_verified_at,
            credential_reference, expires_at, scopes, status_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET
            auth_method = excluded.auth_method,
            account_id = excluded.account_id,
            account_display_name = excluded.account_display_name,
            email = excluded.email,
            connection_status = excluded.connection_status,
            connected_at = excluded.connected_at,
            last_verified_at = excluded.last_verified_at,
            credential_reference = excluded.credential_reference,
            expires_at = excluded.expires_at,
            scopes = excluded.scopes,
            status_message = excluded.status_message
        """,
        (
            pid,
            conn_data.auth_method,
            conn_data.account_id,
            conn_data.account_display_name,
            conn_data.email,
            conn_data.connection_status,
            conn_data.connected_at,
            conn_data.last_verified_at,
            conn_data.credential_reference,
            conn_data.expires_at,
            scopes_json,
            conn_data.status_message,
        ),
    )
    db.commit()


def delete_connection(provider: str) -> bool:
    """Remove connection state for a provider."""
    pid = provider.lower()
    if pid == "anthropic":
        pid = "claude"
    elif pid == "google":
        pid = "gemini"
    elif pid == "grok":
        pid = "xai"

    db = _get_db()
    cur = db.execute("DELETE FROM provider_connections WHERE provider = ?", (pid,))
    db.commit()
    return cur.rowcount > 0


def list_connections() -> list[ProviderConnection]:
    """List all saved provider connections."""
    db = _get_db()
    rows = db.execute("SELECT * FROM provider_connections").fetchall()
    results = []
    for r in rows:
        scopes = []
        if r["scopes"]:
            try:
                scopes = json.loads(r["scopes"])
            except Exception:
                scopes = []
        results.append(
            ProviderConnection(
                provider=r["provider"],
                auth_method=r["auth_method"],
                account_id=r["account_id"],
                account_display_name=r["account_display_name"],
                email=r["email"],
                connection_status=r["connection_status"],
                connected_at=r["connected_at"],
                last_verified_at=r["last_verified_at"],
                credential_reference=r["credential_reference"],
                expires_at=r["expires_at"],
                scopes=scopes,
                status_message=r["status_message"] or "",
            )
        )
    return results
