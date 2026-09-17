"""An account and an API key are independent credentials.

`provider_connections` used to carry a single `connection_status`, so the two
credentials overwrote each other: connecting an account made the API-key card
read "Connected", and removing the API key signed the user out of their
account. These tests pin them apart.
"""
import pytest
from fastapi.testclient import TestClient

from chitragupta.api.app import app
from chitragupta.config import get_settings
from chitragupta.models.connections import (
    ACCOUNT,
    API_KEY,
    ConnectionStatus,
    ProviderConnection,
    get_connection,
    save_connection,
    split_legacy_status,
)
from chitragupta.models.entitlements import provider_credentials
from chitragupta.models.registry import clear_provider_cache

DUAL = ["openai", "claude", "cursor"]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """These tests are about credential bookkeeping, not provider APIs."""
    # Saving a key triggers live model discovery; that is not what is under test.
    # Account detection is left real so the "key does not imply account" assertion
    # stays meaningful.
    monkeypatch.setattr("chitragupta.models.discovery._discover_raw",
                        lambda pid, api_key: ([], {}))


@pytest.fixture(autouse=True)
def _reset():
    for pid in DUAL:
        for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CURSOR_API_KEY"):
            get_settings().set_secret(env, None)
        conn = ProviderConnection(provider=pid)
        save_connection(conn)
    clear_provider_cache()
    yield


# ── the data model ────────────────────────────────────────────────────────
def test_setting_one_credential_leaves_the_other_alone():
    conn = ProviderConnection(provider="openai")
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.set_credential(API_KEY, ConnectionStatus.API_KEY_CONNECTED)
    assert conn.account_connected and conn.api_key_connected

    conn.set_credential(API_KEY, ConnectionStatus.DISCONNECTED)
    assert conn.account_connected is True, "removing the key signed out the account"
    assert conn.api_key_connected is False

    conn.set_credential(ACCOUNT, ConnectionStatus.DISCONNECTED)
    assert conn.rollup() == ConnectionStatus.DISCONNECTED


def test_rollup_prefers_a_working_credential():
    conn = ProviderConnection(provider="claude")
    conn.set_credential(API_KEY, ConnectionStatus.API_KEY_CONNECTED)
    conn.set_credential(ACCOUNT, ConnectionStatus.DISCONNECTED)
    # One credential is dead but the provider is still usable.
    assert conn.rollup() == ConnectionStatus.API_KEY_CONNECTED


def test_per_credential_state_round_trips_through_sqlite():
    conn = get_connection("openai")
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.email = "user@example.com"
    save_connection(conn)

    again = get_connection("openai")
    assert again.account_connected is True
    assert again.api_key_connected is False
    assert again.email == "user@example.com"


@pytest.mark.parametrize("status,auth,expect", [
    (ConnectionStatus.ACCOUNT_CONNECTED, "account", (True, False)),
    (ConnectionStatus.API_KEY_CONNECTED, "api_key", (False, True)),
    (ConnectionStatus.CONNECTED, "api_key", (False, True)),
    (ConnectionStatus.CONNECTED, "account", (True, False)),
    (ConnectionStatus.DISCONNECTED, "account", (False, False)),
])
def test_pre_migration_rows_split_sensibly(status, auth, expect):
    acct, key = split_legacy_status(status, auth)
    from chitragupta.models.connections import CONNECTED_STATUSES
    assert (acct in CONNECTED_STATUSES, key in CONNECTED_STATUSES) == expect


def test_legacy_direct_status_writes_still_work():
    """Callers that set connection_status directly keep their old behaviour."""
    conn = get_connection("cursor")
    conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
    save_connection(conn)
    assert get_connection("cursor").account_connected is True


# ── the reported bug, end to end ─────────────────────────────────────────
@pytest.mark.parametrize("pid,env", [
    ("openai", "OPENAI_API_KEY"),
    ("claude", "ANTHROPIC_API_KEY"),
    ("cursor", "CURSOR_API_KEY"),
])
def test_removing_the_api_key_keeps_the_account_signed_in(client, pid, env):
    conn = get_connection(pid)
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.email = "user@example.com"
    save_connection(conn)
    get_settings().set_secret(env, "sk-test-key")

    r = client.post(f"/api/providers/{pid}/disconnect?scope=api_key")
    assert r.status_code == 200

    after = get_connection(pid)
    assert after.api_key_connected is False
    assert after.account_connected is True, "signing out happened as a side effect"
    assert after.email == "user@example.com"
    assert get_settings().get_secret(env) in (None, "")


@pytest.mark.parametrize("pid,env", [
    ("openai", "OPENAI_API_KEY"),
    ("claude", "ANTHROPIC_API_KEY"),
    ("cursor", "CURSOR_API_KEY"),
])
def test_signing_out_keeps_the_api_key(client, pid, env):
    conn = get_connection(pid)
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.set_credential(API_KEY, ConnectionStatus.API_KEY_CONNECTED)
    save_connection(conn)
    get_settings().set_secret(env, "sk-test-key")

    assert client.post(f"/api/providers/{pid}/disconnect?scope=account").status_code == 200

    after = get_connection(pid)
    assert after.account_connected is False
    assert after.api_key_connected is True, "the saved API key was thrown away"
    assert get_settings().get_secret(env) == "sk-test-key"


def test_clearing_the_key_via_the_key_endpoint_spares_the_account(client):
    conn = get_connection("openai")
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    save_connection(conn)
    get_settings().set_secret("OPENAI_API_KEY", "sk-test")

    r = client.post("/api/providers/openai/key", json={"value": ""})
    assert r.status_code == 200
    assert get_connection("openai").account_connected is True


def test_connecting_a_key_does_not_claim_the_account_is_connected(client):
    r = client.post("/api/providers/deepseek/key", json={"value": "sk-deepseek-test"})
    assert r.status_code == 200
    creds = provider_credentials("deepseek")
    assert creds["api_key"]["connected"] is True
    assert creds["account"]["connected"] is False


def test_scope_all_still_clears_both(client):
    conn = get_connection("openai")
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.set_credential(API_KEY, ConnectionStatus.API_KEY_CONNECTED)
    save_connection(conn)
    get_settings().set_secret("OPENAI_API_KEY", "sk-test")

    assert client.post("/api/providers/openai/disconnect?scope=all").status_code == 200
    after = get_connection("openai")
    assert not after.account_connected and not after.api_key_connected


def test_unknown_scope_is_rejected(client):
    assert client.post("/api/providers/openai/disconnect?scope=bogus").status_code == 400


# ── payload the UI badges from ───────────────────────────────────────────
def test_catalog_reports_each_credential_separately(client):
    body = client.get("/api/models/catalog").json()
    catalog = body.get("catalog", body) if isinstance(body, dict) else body
    for entry in catalog:
        creds = entry.get("credentials")
        assert creds, f"{entry['id']} has no credentials block"
        assert {"account", "api_key"} <= set(creds)
        assert isinstance(creds["api_key"]["connected"], bool)
        assert isinstance(creds["account"]["connected"], bool)


def test_api_key_card_does_not_inherit_account_readiness(client):
    """The exact screenshot bug: account signed in, no key, card said Connected."""
    conn = get_connection("openai")
    conn.set_credential(ACCOUNT, ConnectionStatus.ACCOUNT_CONNECTED)
    conn.email = "user@example.com"
    save_connection(conn)
    get_settings().set_secret("OPENAI_API_KEY", None)
    clear_provider_cache("openai")

    creds = provider_credentials("openai")
    assert creds["api_key"]["connected"] is False, \
        "key card would render a 'Connected' badge with no key stored"
