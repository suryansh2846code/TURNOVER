"""Provider connection state.

A provider can hold **two independent credentials** — a signed-in account
(OAuth / subscription / CLI session) and an API key — and the user may connect
or disconnect either one without touching the other. They are therefore tracked
in separate fields (`account_status`, `api_key_status`); `connection_status` is
kept as a rollup so older readers keep working.

Raw credentials are NEVER stored here. Only their state and the account's
non-secret identity metadata; secrets live in the encrypted secrets store.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
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


# Statuses that mean "this credential can be used right now".
CONNECTED_STATUSES = frozenset({
    ConnectionStatus.CONNECTED,
    ConnectionStatus.ACCOUNT_CONNECTED,
    ConnectionStatus.API_KEY_CONNECTED,
})

ACCOUNT = "account"
API_KEY = "api_key"
CREDENTIAL_KINDS = (ACCOUNT, API_KEY)


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
    # Independent per-credential state. `connection_status` above is a rollup.
    account_status: str = ConnectionStatus.NOT_CONNECTED
    api_key_status: str = ConnectionStatus.NOT_CONNECTED

    @property
    def account_connected(self) -> bool:
        return self.account_status in CONNECTED_STATUSES

    @property
    def api_key_connected(self) -> bool:
        return self.api_key_status in CONNECTED_STATUSES

    def set_credential(self, kind: str, status: str) -> None:
        """Set one credential's state and refresh the rollup. The other
        credential is left exactly as it was."""
        if kind == ACCOUNT:
            self.account_status = status
        elif kind == API_KEY:
            self.api_key_status = status
        else:
            raise ValueError(f"unknown credential kind {kind!r}")
        self.connection_status = self.rollup()

    def rollup(self) -> str:
        """A single status for readers that don't care which credential it is."""
        if self.account_connected:
            return ConnectionStatus.ACCOUNT_CONNECTED
        if self.api_key_connected:
            return ConnectionStatus.API_KEY_CONNECTED
        for candidate in (ConnectionStatus.ACCOUNT_FOUND_ON_COMPUTER,
                          ConnectionStatus.REAUTHORIZATION_REQUIRED,
                          ConnectionStatus.TOKEN_EXPIRED,
                          ConnectionStatus.ERROR):
            if candidate in (self.account_status, self.api_key_status):
                return candidate
        # Explicit user intent outranks "never connected".
        if ConnectionStatus.DISCONNECTED in (self.account_status, self.api_key_status):
            return ConnectionStatus.DISCONNECTED
        return ConnectionStatus.NOT_CONNECTED

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scopes"] = list(self.scopes)
        d["account_connected"] = self.account_connected
        d["api_key_connected"] = self.api_key_connected
        return d


def split_legacy_status(status: str, auth_method: str) -> tuple[str, str]:
    """Derive (account_status, api_key_status) from a pre-migration row."""
    if status == ConnectionStatus.ACCOUNT_CONNECTED:
        return status, ConnectionStatus.NOT_CONNECTED
    if status == ConnectionStatus.API_KEY_CONNECTED:
        return ConnectionStatus.NOT_CONNECTED, status
    if status == ConnectionStatus.CONNECTED:
        # Generic "connected" — attribute it to whichever method was recorded.
        if auth_method == "api_key":
            return ConnectionStatus.NOT_CONNECTED, status
        return status, ConnectionStatus.NOT_CONNECTED
    # DISCONNECTED / NOT_CONNECTED / errors applied to the provider as a whole.
    return status, status


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


def _migrate(c: sqlite3.Connection) -> None:
    """Add the per-credential columns and backfill them from the old rollup."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(provider_connections)")}
    added = False
    for col in ("account_status", "api_key_status"):
        if col not in cols:
            c.execute(f"ALTER TABLE provider_connections ADD COLUMN {col} TEXT")
            added = True
    if added:
        for row in c.execute(
            "SELECT provider, connection_status, auth_method FROM provider_connections"
        ).fetchall():
            acct, key = split_legacy_status(row["connection_status"], row["auth_method"])
            c.execute(
                "UPDATE provider_connections SET account_status=?, api_key_status=? "
                "WHERE provider=?",
                (acct, key, row["provider"]),
            )
        c.commit()


def _get_db() -> sqlite3.Connection:
    path = get_settings().home / "agents.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    _migrate(c)
    return c


def _row_to_connection(row: sqlite3.Row) -> ProviderConnection:
    scopes: list[str] = []
    if row["scopes"]:
        try:
            scopes = json.loads(row["scopes"])
        except Exception:
            scopes = []
    status = row["connection_status"]
    acct = row["account_status"]
    key = row["api_key_status"]
    if acct is None or key is None:
        # Row written before the per-credential split.
        acct, key = split_legacy_status(status, row["auth_method"])
    return ProviderConnection(
        provider=row["provider"],
        auth_method=row["auth_method"],
        account_id=row["account_id"],
        account_display_name=row["account_display_name"],
        email=row["email"],
        connection_status=status,
        connected_at=row["connected_at"],
        last_verified_at=row["last_verified_at"],
        credential_reference=row["credential_reference"],
        expires_at=row["expires_at"],
        scopes=scopes,
        status_message=row["status_message"] or "",
        account_status=acct,
        api_key_status=key,
    )


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
        return _row_to_connection(row)

    return ProviderConnection(provider=pid)


def save_connection(conn_data: ProviderConnection) -> None:
    """Save or update provider connection state.

    Callers that still set `connection_status` directly (rather than
    `set_credential`) are honoured: when the rollup disagrees with what they
    set, the explicit value wins and is split across both credentials — the
    pre-split behaviour.
    """
    db = _get_db()
    pid = conn_data.provider.lower()
    scopes_json = json.dumps(conn_data.scopes or [])

    if conn_data.connection_status != conn_data.rollup():
        conn_data.account_status, conn_data.api_key_status = split_legacy_status(
            conn_data.connection_status, conn_data.auth_method
        )

    db.execute(
        """
        INSERT INTO provider_connections (
            provider, auth_method, account_id, account_display_name, email,
            connection_status, connected_at, last_verified_at,
            credential_reference, expires_at, scopes, status_message,
            account_status, api_key_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            status_message = excluded.status_message,
            account_status = excluded.account_status,
            api_key_status = excluded.api_key_status
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
            conn_data.account_status,
            conn_data.api_key_status,
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
    return [_row_to_connection(r) for r in rows]
