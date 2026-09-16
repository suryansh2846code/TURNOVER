"""Which agent can reach which tools — and being told when one cannot.

The bug this file exists for, from a real machine: a user connected Notion —
signed in, twenty-five working tools — and asked their agent to summarise a
page. It answered out of Notion's *notification emails* and said the connector
was probably still syncing. One step, `search_brain`.

Nothing was broken. The agent was built before Notion was connected, so it had
no `mcp` sentinel; `describe()` offers the sentinel only when something is
behind it, so the option did not exist to tick at build time; and nothing ever
told anyone to go back.

Contract: docs/development/agent-tool-grants.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from lodestone.agents import grants, mcp_tools
from lodestone.agents.agent import AgentMemory
from lodestone.agents.custom import get_custom_store
from lodestone.agents.library import BASE_TOOLS
from lodestone.agents.mcp_tools import SENTINEL
from lodestone.agents.presets import PRESETS

#: The agent from the report, exactly as it was stored.
CHOTU_TOOLS = ["search_brain", "remember", "list_entities", "web_search",
               "add_task", "list_tasks", "complete_task", "gmail_search"]


@dataclass
class MCPToolRef:
    qualified_name: str
    server_id: str
    server_label: str
    tool: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    writes: bool = False


NOTION_SEARCH = MCPToolRef("notion:search", "notion", "Notion", "search",
                           "Search the user's Notion workspace.")
NOTION_PAGES = MCPToolRef("notion:list_pages", "notion", "Notion", "list_pages",
                          "List recent pages.")


@pytest.fixture(autouse=True)
def _no_stale_discovery():
    mcp_tools.clear_cache()
    yield
    mcp_tools.clear_cache()


@pytest.fixture
def notion(monkeypatch):
    """Notion connected and answering, the way it was on the real machine."""
    supplier = SimpleNamespace(
        list_tools=lambda: [NOTION_SEARCH, NOTION_PAGES],
        call_tool=lambda *a, **k: "ok")
    monkeypatch.setattr(mcp_tools, "_supplier", lambda: supplier)
    mcp_tools.clear_cache()
    return supplier


@pytest.fixture
def no_connectors(monkeypatch):
    monkeypatch.setattr(mcp_tools, "_supplier", lambda: None)
    monkeypatch.setattr(grants, "_configured_connectors", list)
    mcp_tools.clear_cache()


@pytest.fixture
def chotu():
    """A custom agent built before the connector existed."""
    store = get_custom_store()
    agent = store.create("chotu", role="general", system_prompt="help",
                         tools=list(CHOTU_TOOLS))
    yield agent
    store.delete(agent.id)


# ── the reproduction ─────────────────────────────────────────────────────
def test_the_agent_from_the_report_cannot_reach_the_connected_notion(chotu, notion):
    """The starting state. If this ever passes, the bug is back."""
    assert not grants.reaches_connectors(chotu)


def test_the_gap_is_surfaced_rather_than_left_to_be_discovered(chotu, notion):
    """The missing half: nothing ever told anyone to go back."""
    out = grants.connector_gaps()
    assert "Notion" in out["connectors"]
    assert out["tool_count"] == 2
    assert chotu.id in [a["agent_id"] for a in out["agents"]], (
        "the agent that cannot see Notion was not named")


def test_the_option_now_exists_to_tick(chotu, notion):
    """It did not, at build time — which is the whole cause."""
    view = grants.for_agent(chotu.id)
    sentinel = next(r for r in view["tools"] if r["name"] == SENTINEL)
    assert sentinel["state"] == "available"
    assert view["reaches_connectors"] is False


def test_granting_the_category_closes_it(chotu, notion):
    get_custom_store().update(chotu.id, tools=[*CHOTU_TOOLS, SENTINEL])
    view = grants.for_agent(chotu.id)

    assert view["reaches_connectors"] is True
    assert chotu.id not in [a["agent_id"] for a in grants.connector_gaps()["agents"]]

    # Notion's tools now read as granted, and say how.
    notion_rows = [r for r in view["tools"] if r["connector"] == "Notion"]
    assert notion_rows, "Notion's tools are not listed at all"
    assert all(r["state"] == "granted" for r in notion_rows)
    assert all(r["via"] == "category" for r in notion_rows), (
        "a tool reached through the category must say so — it is not in the "
        "stored list, so a consumer must not offer to untick it")


# ── nobody is granted anything behind their back ─────────────────────────
def test_an_existing_agent_is_never_silently_granted(chotu, notion):
    """Connector access is a permission the user set. Surfacing the gap is in
    scope; closing it without asking is not."""
    before = list(get_custom_store().get(chotu.id).tools)
    grants.connector_gaps()
    grants.for_agent(chotu.id)
    assert list(get_custom_store().get(chotu.id).tools) == before


# ── the default for new agents ───────────────────────────────────────────
def test_a_new_custom_agent_can_reach_connectors_from_the_start(notion):
    """A preset gets this. A custom agent is an agent."""
    store = get_custom_store()
    fresh = store.create("fresh one", role="x", system_prompt="y")
    try:
        assert SENTINEL in fresh.tools
        assert grants.reaches_connectors(fresh)
        assert list(fresh.tools) == list(BASE_TOOLS), (
            "a custom agent should start from the same base as a preset")
    finally:
        store.delete(fresh.id)


def test_choosing_no_tools_is_still_respected():
    """The default is for the unspecified case, not an override."""
    store = get_custom_store()
    narrow = store.create("narrow", tools=["search_brain"])
    try:
        assert narrow.tools == ["search_brain"]
    finally:
        store.delete(narrow.id)


# ── changing a custom agent keeps what it has ────────────────────────────
def test_an_update_keeps_the_conversation_and_the_model(chotu):
    """The reason this is a PATCH and not delete-and-recreate."""
    from lodestone.agents.agent_models import get_agent_model, set_agent_model

    AgentMemory().append(chotu.id, "user", "something worth keeping")
    set_agent_model(chotu.id, "openai", "gpt-5.5")

    updated = get_custom_store().update(chotu.id, tools=[*CHOTU_TOOLS, SENTINEL])

    assert updated is not None
    assert updated.id == chotu.id, "the id moved; history is keyed by it"
    assert any("worth keeping" in (r["content"] or "")
               for r in AgentMemory().history(chotu.id, limit=10))
    assert get_agent_model(chotu.id) == ("openai", "gpt-5.5")


def test_renaming_does_not_move_the_id(chotu):
    updated = get_custom_store().update(chotu.id, name="Chotu The Second")
    assert updated.id == chotu.id
    assert updated.name == "Chotu The Second"


def test_an_absent_field_is_left_alone(chotu):
    """So changing one thing cannot blank another by omission."""
    get_custom_store().update(chotu.id, name="Renamed")
    again = get_custom_store().get(chotu.id)
    assert again.tools == CHOTU_TOOLS
    assert again.system_prompt == "help"


def test_updating_something_that_is_not_a_custom_agent_returns_nothing():
    assert get_custom_store().update("chief-of-staff", tools=["search_brain"]) is None


# ── the view tells the truth ─────────────────────────────────────────────
def test_the_sentinel_is_offered_even_with_nothing_connected(chotu, no_connectors):
    """Hiding it is precisely what produced the bug. A standing grant set in
    advance is a real answer to "what could this agent have"."""
    view = grants.for_agent(chotu.id)
    sentinel = next(r for r in view["tools"] if r["name"] == SENTINEL)
    assert sentinel["state"] == "available"
    assert sentinel["reason"] == grants.NOTHING_CONNECTED
    assert view["connector_tool_count"] == 0


def test_a_connector_contributing_nothing_says_why_where_its_tools_would_be(
        chotu, monkeypatch):
    """A tool row must never claim an agent can do something it cannot — and a
    silently empty group is the same lie by omission."""
    monkeypatch.setattr(mcp_tools, "_supplier", lambda: None)
    monkeypatch.setattr(
        grants, "_configured_connectors",
        lambda: [("Notion", SimpleNamespace(id="notion", name="Notion"))])
    monkeypatch.setattr(
        grants, "_why_silent",
        lambda spec, label: f"{label} is signed out — reconnect it under Connectors.")
    mcp_tools.clear_cache()

    view = grants.for_agent(chotu.id)
    blocked = [r for r in view["tools"] if r["state"] == "unavailable"]
    assert len(blocked) == 1
    row = blocked[0]
    assert row["connector"] == "Notion"
    assert "signed out" in row["reason"]
    assert row["name"] == "", "there is nothing to grant, which is the point"


def test_a_working_connector_is_never_reported_as_blocked(chotu, notion, monkeypatch):
    monkeypatch.setattr(
        grants, "_configured_connectors",
        lambda: [("Notion", SimpleNamespace(id="notion", name="Notion"))])
    view = grants.for_agent(chotu.id)
    assert not [r for r in view["tools"] if r["state"] == "unavailable"]


def test_every_builtin_is_accounted_for(chotu, no_connectors):
    from lodestone.agents.tools import TOOL_DEFS

    view = grants.for_agent(chotu.id)
    listed = {r["name"] for r in view["tools"] if r["source"] == "builtin"}
    assert listed == set(TOOL_DEFS)

    granted = {r["name"] for r in view["tools"] if r["state"] == "granted"}
    assert granted == set(CHOTU_TOOLS), "the view disagrees with what is stored"


def test_the_protocol_acronym_is_never_the_part_a_person_reads(chotu, notion):
    """tests/test_connector_catalog_ui.py pins this for the catalogue; the same
    rule covers this endpoint."""
    view = grants.for_agent(chotu.id)
    for row in view["tools"]:
        assert "mcp" not in row["label"].lower(), row
        assert "mcp" not in row["reason"].lower(), row
    sentinel = next(r for r in view["tools"] if r["name"] == SENTINEL)
    assert sentinel["label"] == "Everything my connectors can read"


# ── presets ──────────────────────────────────────────────────────────────
def test_a_preset_says_it_cannot_be_edited_and_why():
    """Per agent, from the server — not inferred by the UI."""
    view = grants.for_agent("chief-of-staff")
    assert view["editable"] is False
    assert view["custom"] is False
    assert "Chief of Staff" in view["editable_reason"]


def test_custom_and_editable_are_reported_separately(chotu):
    view = grants.for_agent(chotu.id)
    assert view["custom"] is True and view["editable"] is True


def test_every_preset_already_reaches_connectors(notion):
    """Which is why the reported bug could only be a custom agent."""
    for agent in PRESETS.values():
        assert grants.reaches_connectors(agent), f"{agent.id} cannot"


# ── validation ───────────────────────────────────────────────────────────
def test_an_unknown_tool_is_named_rather_than_dropped(notion):
    assert grants.unknown_tools(["search_brain", SENTINEL]) == []
    assert grants.unknown_tools(["notion_search"]) == []
    assert grants.unknown_tools(["not_a_tool", "also_not"]) == ["not_a_tool", "also_not"]


# ── over HTTP ────────────────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient

    from lodestone.api.app import app
    return TestClient(app)


def test_the_per_agent_view_is_reachable(chotu, notion):
    r = _client().get(f"/api/agents/{chotu.id}/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == chotu.id
    assert body["reaches_connectors"] is False
    assert any(t["name"] == SENTINEL for t in body["tools"])


def test_asking_about_an_agent_that_does_not_exist_is_a_404():
    assert _client().get("/api/agents/nobody/tools").status_code == 404


def test_the_agents_list_says_which_ones_cannot_reach_connectors(chotu, notion):
    rows = {a["id"]: a for a in _client().get("/api/agents").json()["agents"]}
    assert rows[chotu.id]["reaches_connectors"] is False
    assert rows["chief-of-staff"]["reaches_connectors"] is True


def test_patching_tools_works_and_returns_the_fresh_view(chotu, notion):
    r = _client().patch(f"/api/agents/custom/{chotu.id}",
                        json={"tools": [*CHOTU_TOOLS, SENTINEL]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reaches_connectors"] is True, "no second round trip should be needed"
    assert get_custom_store().get(chotu.id).tools[-1] == SENTINEL


def test_patching_a_preset_is_refused_by_the_server(notion):
    """The boundary is the server's to enforce, not the UI's to remember."""
    r = _client().patch("/api/agents/custom/chief-of-staff",
                        json={"tools": ["search_brain"]})
    assert r.status_code == 404
    assert PRESETS["chief-of-staff"].tools, "the preset was altered anyway"


def test_patching_an_unknown_tool_names_it(chotu, notion):
    r = _client().patch(f"/api/agents/custom/{chotu.id}",
                        json={"tools": ["search_brain", "not_a_tool"]})
    assert r.status_code == 400
    assert "not_a_tool" in r.json()["detail"]
    assert get_custom_store().get(chotu.id).tools == CHOTU_TOOLS, (
        "a rejected update still changed the agent")


def test_the_gaps_endpoint_answers_the_just_connected_question(chotu, notion):
    body = _client().get("/api/agents/connector-gaps").json()
    assert "Notion" in body["connectors"]
    assert chotu.id in [a["agent_id"] for a in body["agents"]]


def test_with_no_connectors_there_is_nothing_to_say(chotu, no_connectors):
    body = _client().get("/api/agents/connector-gaps").json()
    assert body == {"connectors": [], "tool_count": 0, "agents": []}


# ── the default has to survive the request, not just the store ────────────


def _built_through_the_api(body: dict) -> dict:
    """Create an agent the way the builder does, and read back what it got."""
    from fastapi.testclient import TestClient

    from lodestone.api.app import app

    client = TestClient(app)
    created = client.post("/api/agents/custom", json=body).json()
    try:
        return client.get(f"/api/agents/{created['id']}/tools").json()
    finally:
        client.delete(f"/api/agents/custom/{created['id']}")


def test_an_agent_built_without_picking_tools_still_works(notion):
    """"Unspecified" has to survive the HTTP layer.

    `create()` distinguishes `None` — the caller expressed no opinion, give it
    the standard set — from `[]`, which deliberately wants none. That
    distinction *is* decision D, and it was lost one layer up: the request model
    declared `tools: list[str] = []`, so the API could never send `None`. An
    agent created from the builder without touching the tool list therefore got
    nothing at all — worse than the five-tool default it replaced, on the only
    path the UI uses.

    The sibling test above calls the store directly and passes either way, which
    is exactly why this one has to go through the request.
    """
    view = _built_through_the_api({"name": "zz unspecified"})

    assert [t for t in view["tools"] if t["state"] == "granted"], (
        "an agent built with the defaults was given no tools at all")
    assert view["reaches_connectors"], (
        "decision D: a new custom agent holds the standing connector grant, so "
        "it works the day a connector is added")


def test_asking_for_no_tools_is_still_honoured_through_the_api(notion):
    """The default is for the unspecified case, never an override — and that
    has to stay true once `None` and `[]` can both reach the handler."""
    view = _built_through_the_api({"name": "zz empty", "tools": []})

    assert not [t for t in view["tools"] if t["state"] == "granted"]
    assert not view["reaches_connectors"]
