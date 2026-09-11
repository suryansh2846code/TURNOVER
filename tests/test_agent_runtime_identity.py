"""Tests for agent runtime identity and authoritative runtime context injection."""
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from lodestone.agents import (
    Agent,
    TurnResult,
    build_runtime_identity,
    format_runtime_context_prompt,
    run_turn,
)
from lodestone.api.app import app
from lodestone.models.base import LLMProvider, Message


class DummyProvider(LLMProvider):
    name = "openai"
    model = "gpt-5.6-terra"

    def is_ready(self) -> tuple[bool, str]:
        return True, ""

    def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
        # Return what was in the system messages for verification
        sys_msgs = [m.content for m in messages if m.role == "system"]
        return MagicMock(text="\n---\n".join(sys_msgs), wants_tools=False, tool_calls=[])


def test_build_runtime_identity_basic():
    agent = Agent(id="inbox", name="Inbox", role="email & communications", system_prompt="Help with emails")
    provider = DummyProvider()
    identity = build_runtime_identity(agent, provider)

    assert identity["application"] == "Lodestone"
    assert identity["agent_id"] == "inbox"
    assert identity["agent_name"] == "Inbox"
    assert identity["agent_role"] == "email & communications"
    assert identity["provider"] == "OpenAI"
    assert identity["provider_name"] == "openai"
    assert identity["model"] == "gpt-5.6-terra"


def test_build_runtime_identity_codex_harness(monkeypatch):
    agent = Agent(id="social", name="Social Manager", role="social media manager", system_prompt="Help with socials")
    provider = DummyProvider()

    # When get_chatgpt_access_token returns a token and provider has no explicit api_key:
    with patch("lodestone.models.chatgpt_auth.get_chatgpt_access_token", return_value="test-token"):
        identity = build_runtime_identity(agent, provider)
        assert identity["harness"] == "Codex harness"

    prompt = format_runtime_context_prompt(identity)
    assert "RUNTIME CONTEXT — AUTHORITATIVE" in prompt
    assert "Application: Lodestone" in prompt
    assert "Selected Agent: Social Manager" in prompt
    assert "Agent Role: social media manager" in prompt
    assert "Provider: OpenAI" in prompt
    assert "Model: gpt-5.6-terra" in prompt
    assert "Harness: Codex harness" in prompt
    assert "running on OpenAI's `gpt-5.6-terra` model through the Codex harness" in prompt


def test_format_runtime_context_prompt():
    identity = {
        "application": "Lodestone",
        "agent_id": "inbox",
        "agent_name": "Inbox",
        "agent_role": "email & communications",
        "provider": "Anthropic",
        "model": "claude-3-7-sonnet",
        "harness": None,
    }
    prompt = format_runtime_context_prompt(identity)
    assert "RUNTIME CONTEXT — AUTHORITATIVE" in prompt
    assert "Application: Lodestone" in prompt
    assert "Selected Agent: Inbox" in prompt
    assert "Provider: Anthropic" in prompt
    assert "Model: claude-3-7-sonnet" in prompt
    assert "running on Anthropic's `claude-3-7-sonnet` model." in prompt


def test_run_turn_injects_authoritative_runtime_context(monkeypatch):
    dummy = DummyProvider()
    monkeypatch.setattr("lodestone.agents.runtime.get_provider", lambda p, m: dummy)

    res = run_turn("inbox", "which model are you using")
    assert isinstance(res, TurnResult)
    assert res.runtime_identity["application"] == "Lodestone"
    assert res.runtime_identity["agent_id"] == "inbox"
    assert res.runtime_identity["agent_name"] == "Inbox"
    assert res.runtime_identity["provider"] == "OpenAI"
    assert res.runtime_identity["model"] == "gpt-5.6-terra"

    # Verify runtime context prompt was delivered to the model
    assert "RUNTIME CONTEXT — AUTHORITATIVE" in res.reply
    assert "Selected Agent: Inbox" in res.reply
    assert "Model: gpt-5.6-terra" in res.reply

    # Verify serialization
    d = res.as_dict()
    assert "runtime_identity" in d
    assert d["runtime_identity"]["agent_id"] == "inbox"


def test_api_chat_and_welcome_include_runtime_identity(monkeypatch):
    client = TestClient(app)

    # 1. Chat endpoint
    resp = client.post("/api/agents/personal/chat", json={
        "message": "Hello status test",
        "provider": "mock",
        "model": "mock-test-model",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "runtime_identity" in data
    assert data["runtime_identity"]["agent_id"] == "personal"
    assert data["runtime_identity"]["application"] == "Lodestone"
    assert data["runtime_identity"]["model"] == "mock-test-model"

    # 2. Welcome endpoint
    resp = client.post("/api/agents/personal/welcome", json={
        "message": "welcome",
        "provider": "mock",
        "model": "mock-welcome-model",
    })
    assert resp.status_code == 200
    wdata = resp.json()
    assert "runtime_identity" in wdata
    assert wdata["runtime_identity"]["agent_id"] == "personal"
    assert wdata["runtime_identity"]["model"] == "mock-welcome-model"
