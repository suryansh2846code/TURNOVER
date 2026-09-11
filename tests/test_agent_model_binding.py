"""Tests for per-agent model binding subsystem."""
import pytest
from fastapi.testclient import TestClient

from lodestone.agents.agent_models import (
    get_agent_model,
    set_agent_model,
    clear_agent_model,
    list_agent_models,
)
from lodestone.agents.presets import get_agent, list_agents
from lodestone.agents.runtime import run_turn
from lodestone.api.app import app


@pytest.fixture(autouse=True)
def clean_agent_models():
    """Clear test bindings before and after tests."""
    for agent_id in ["inbox", "launch", "research", "personal", "test-agent"]:
        clear_agent_model(agent_id)
    yield
    for agent_id in ["inbox", "launch", "research", "personal", "test-agent"]:
        clear_agent_model(agent_id)


def test_agent_model_crud():
    """Verify persisting, reading, and clearing an agent's assigned model."""
    assert get_agent_model("inbox") == (None, None)

    # Assign Claude 3.7 Sonnet to Inbox agent
    res = set_agent_model("inbox", "claude", "claude-3-7-sonnet-latest")
    assert res["agent_id"] == "inbox"
    assert res["provider"] == "claude"
    assert res["model"] == "claude-3-7-sonnet-latest"

    prov, model = get_agent_model("inbox")
    assert prov == "claude"
    assert model == "claude-3-7-sonnet-latest"

    # Assign Gemini 2.5 Flash to Research agent
    set_agent_model("research", "gemini", "gemini-2.5-flash")

    # List all assigned models
    all_models = list_agent_models()
    assert "inbox" in all_models
    assert all_models["inbox"]["provider"] == "claude"
    assert "research" in all_models
    assert all_models["research"]["provider"] == "gemini"

    # Clear Inbox model assignment
    cleared = clear_agent_model("inbox")
    assert cleared is True
    assert get_agent_model("inbox") == (None, None)


def test_agent_instance_overlay():
    """Verify get_agent() and list_agents() reflect the bound model."""
    set_agent_model("inbox", "claude", "claude-3-7-sonnet-latest")
    set_agent_model("launch", "xai", "grok-2-latest")

    inbox = get_agent("inbox")
    assert inbox.model_provider == "claude"
    assert inbox.model_name == "claude-3-7-sonnet-latest"

    launch = get_agent("launch")
    assert launch.model_provider == "xai"
    assert launch.model_name == "grok-2-latest"

    # Research has no override
    research = get_agent("research")
    assert research.model_provider is None

    # Check list_agents()
    all_agents = {a.id: a for a in list_agents()}
    assert all_agents["inbox"].model_provider == "claude"
    assert all_agents["launch"].model_provider == "xai"
    assert all_agents["research"].model_provider is None


def test_runtime_uses_agent_bound_model(monkeypatch):
    """Verify run_turn() executes with the agent's bound model when no turn override is passed."""
    set_agent_model("personal", "mock", "mock-custom-model")

    turn = run_turn("personal", "Hello from user")
    assert turn.provider == "mock"
    assert turn.model == "mock-custom-model"


def test_api_endpoints():
    """Verify REST API endpoints for model catalog and agent model binding."""
    client = TestClient(app)

    # 1. Get model catalog
    resp = client.get("/api/models/catalog")
    assert resp.status_code == 200
    catalog = resp.json()["catalog"]
    assert any(c["id"] == "gemini" for c in catalog)
    assert any(c["id"] == "xai" for c in catalog)
    assert any(c["id"] == "claude" for c in catalog)

    # 2. Get initial agent model
    resp = client.get("/api/agents/inbox/model")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "inbox"
    assert data["is_override"] is False

    # 3. Set agent model
    resp = client.post("/api/agents/inbox/model", json={
        "provider": "gemini",
        "model": "gemini-2.5-pro",
    })
    assert resp.status_code == 200
    assert resp.json()["provider"] == "gemini"
    assert resp.json()["model"] == "gemini-2.5-pro"

    # 4. Verify get reflects change
    resp = client.get("/api/agents/inbox/model")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "gemini"
    assert data["model"] == "gemini-2.5-pro"
    assert data["is_override"] is True

    # 5. Check GET /api/agents includes model info
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    inbox_agent = next(a for a in agents if a["id"] == "inbox")
    assert inbox_agent["model_provider"] == "gemini"
    assert inbox_agent["model_name"] == "gemini-2.5-pro"

    # 6. Delete agent model override
    resp = client.delete("/api/agents/inbox/model")
    assert resp.status_code == 200
    assert resp.json()["cleared"] is True

    # 7. Verify cleared
    resp = client.get("/api/agents/inbox/model")
    assert resp.json()["is_override"] is False
