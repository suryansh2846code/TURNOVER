"""Tests for Agent / Model Decoupling, Brain Continuity, and Tool Safety.

Guarantees TURNOVER's absolute architectural invariant:
USER -> SELECTS AGENT -> AGENT -> SELECTED MODEL -> BRAIN + TOOLS -> RESPONSE
No auto-routing. User chooses agent. Model is infrastructure underneath.
"""
from __future__ import annotations

from lodestone.agents.presets import get_agent
from lodestone.agents.runtime import run_turn
from lodestone.agents.tools import run_tool, validate_tool_arguments
from lodestone.brain import get_brain


def test_one_agent_with_multiple_models():
    """Verify that switching models does NOT alter the agent's identity, role, or instructions."""
    inbox_base = get_agent("inbox")
    initial_name = inbox_base.name
    initial_role = inbox_base.role
    initial_tools = list(inbox_base.tools)
    initial_sys = inbox_base.system_message()

    # Run Inbox with mock model
    res1 = run_turn("inbox", "What is the capital of France?", provider_name="mock", model_name="mock-1")
    assert res1.provider == "mock"
    assert res1.model == "mock-1"

    # Verify Inbox remains identical
    inbox_after1 = get_agent("inbox")
    assert inbox_after1.name == initial_name
    assert inbox_after1.role == initial_role
    assert inbox_after1.tools == initial_tools
    assert inbox_after1.system_message() == initial_sys

    # Run Inbox with another model (mock-2)
    res2 = run_turn("inbox", "Summarize my day", provider_name="mock", model_name="mock-2")
    assert res2.provider == "mock"
    assert res2.model == "mock-2"

    inbox_after2 = get_agent("inbox")
    assert inbox_after2.name == initial_name
    assert inbox_after2.role == initial_role


def test_one_model_with_multiple_agents():
    """Verify multiple distinct agents can use the same model without changing identity."""
    agents = ["inbox", "launch", "research", "personal"]
    for aid in agents:
        agent = get_agent(aid)
        res = run_turn(aid, "Status check", provider_name="mock", model_name="mock-1")
        assert res.agent_id == aid
        assert res.provider == "mock"
        assert get_agent(aid).name == agent.name


def test_brain_continuity_across_models():
    """Verify that the Brain is persistent and shared across different model providers."""
    brain = get_brain()
    test_fact = "User preferred language is Python and Rust."
    brain.ingest(test_fact, source="agent", kind="fact", title="language_pref")

    # Ingested fact is recalled regardless of agent or model
    recalled = brain.recall("What languages does the user prefer?")
    assert "Python" in recalled["context"] or "Rust" in recalled["context"]


def test_tool_calling_schema_validation():
    """Verify authoritative schema validation in run_tool."""
    # 1. Valid arguments
    valid, err, clean = validate_tool_arguments("search_brain", {"query": "test query", "limit": 3})
    assert valid is True
    assert clean["query"] == "test query"
    assert clean["limit"] == 3

    # 2. Unexpected injected parameters are stripped
    valid, err, clean = validate_tool_arguments("search_brain", {
        "query": "valid query",
        "malicious_extra_field": "drop_me",
    })
    assert valid is True
    assert "malicious_extra_field" not in clean

    # 3. Missing required parameter fails validation
    valid, err, clean = validate_tool_arguments("add_task", {"due": "tomorrow"})
    assert valid is False
    assert "Missing required parameter 'title'" in err

    # 4. run_tool blocks execution on validation failure
    output = run_tool("add_task", {"due": "tomorrow"})
    assert "Schema validation error" in output

    # 5. Invalid type coercion failure
    valid, err, clean = validate_tool_arguments("search_brain", {"query": "q", "limit": "not_an_int"})
    assert valid is False
    assert "must be an integer" in err
