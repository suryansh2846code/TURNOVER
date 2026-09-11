"""Unit tests for ProviderConnection persistence and state management."""
from __future__ import annotations

from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.models.connections import (
    ConnectionStatus,
    ProviderConnection,
    delete_connection,
    get_connection,
    list_connections,
    save_connection,
)


def test_provider_connection_crud():
    """Verify SQLite CRUD on ProviderConnection state."""
    test_conn = ProviderConnection(
        provider="test_prov",
        auth_method="api_key",
        account_id="acc_123",
        account_display_name="Test User",
        email="test@example.com",
        connection_status=ConnectionStatus.API_KEY_CONNECTED,
        connected_at="2026-09-11T10:00:00Z",
        last_verified_at="2026-09-11T10:05:00Z",
        credential_reference="TEST_API_KEY",
        scopes=["chat:write", "models:read"],
        status_message="Connected via test key",
    )

    save_connection(test_conn)

    retrieved = get_connection("test_prov")
    assert retrieved.provider == "test_prov"
    assert retrieved.email == "test@example.com"
    assert retrieved.account_display_name == "Test User"
    assert retrieved.connection_status == ConnectionStatus.API_KEY_CONNECTED
    assert retrieved.credential_reference == "TEST_API_KEY"
    assert "models:read" in retrieved.scopes

    all_conns = list_connections()
    assert any(c.provider == "test_prov" for c in all_conns)

    # Delete
    deleted = delete_connection("test_prov")
    assert deleted is True
    assert get_connection("test_prov").connection_status == ConnectionStatus.NOT_CONNECTED


def test_provider_connections_api_endpoints():
    """Verify GET /api/providers/connections and disconnect endpoint."""
    client = TestClient(app)

    # 1. List connections
    resp = client.get("/api/providers/connections")
    assert resp.status_code == 200
    assert "connections" in resp.json()

    # 2. Disconnect test
    resp = client.post("/api/providers/openai/disconnect")
    assert resp.status_code == 200
    assert resp.json()["disconnected"] is True
    assert resp.json()["connection"]["connection_status"] == ConnectionStatus.DISCONNECTED

    # 3. Refresh test
    resp = client.post("/api/providers/mock/refresh")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["ready"] is True
