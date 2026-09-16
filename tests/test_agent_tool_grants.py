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
from lodestone.agents.tool_overrides import get_tool_overrides

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
    agent = store.create("chotu-under-test", role="general",
                         system_prompt="help", tools=list(CHOTU_TOOLS))
    yield agent
    store.delete(agent.id)          # which now reaps the override too


@pytest.fixture(autouse=True)
def _no_leaked_overrides():
    """An override outlives the object under test unless something clears it."""
    yield
    for agent_id in ("research", "chief-of-staff", "chotu-under-test"):
        get_tool_overrides().clear(agent_id)
    # The roster is persisted, so a test that adds to it and walks away leaks
    # into every later test that asks what a fresh install looks like.
    from lodestone.agents.library import remove_from_roster
    for agent_id in ("chief-of-staff", "inbox"):
        remove_from_roster(agent_id)


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
    get_tool_overrides().set(chotu.id, [*CHOTU_TOOLS, SENTINEL])
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


# ── changing what an agent may use ───────────────────────────────────────
def test_a_change_keeps_the_conversation_and_the_model(chotu):
    """Recorded as an override, so nothing is recreated — which is why the chat
    history and the model binding, both keyed by the agent id, survive."""
    from lodestone.agents.agent_models import get_agent_model, set_agent_model
    from lodestone.agents.presets import get_agent

    AgentMemory().append(chotu.id, "user", "something worth keeping")
    set_agent_model(chotu.id, "openai", "gpt-5.5")

    get_tool_overrides().set(chotu.id, [*CHOTU_TOOLS, SENTINEL])

    assert get_agent(chotu.id).id == chotu.id
    assert any("worth keeping" in (r["content"] or "")
               for r in AgentMemory().history(chotu.id, limit=10))
    assert get_agent_model(chotu.id) == ("openai", "gpt-5.5")


def test_a_preset_can_be_changed_and_put_back(notion):
    """The reversal: everything is editable, because a change is an override —
    so the shipped definition is still there to return to."""
    from lodestone.agents.presets import PRESETS, get_agent

    shipped = list(PRESETS["research"].tools)
    try:
        get_tool_overrides().set("research", ["search_brain"])
        assert get_agent("research").tools == ["search_brain"]
        assert grants.for_agent("research")["overridden"] is True
        # The constant in code is untouched, which is what lets a later release
        # improve the preset for everyone who has not changed it.
        assert list(PRESETS["research"].tools) == shipped

        get_tool_overrides().clear("research")
        assert get_agent("research").tools == shipped
        assert grants.for_agent("research")["overridden"] is False
    finally:
        get_tool_overrides().clear("research")


def test_the_default_is_reported_so_reset_is_possible(chotu, notion):
    view = grants.for_agent(chotu.id)
    assert view["default_tools"] == CHOTU_TOOLS
    assert view["overridden"] is False

    get_tool_overrides().set(chotu.id, ["search_brain"])
    view = grants.for_agent(chotu.id)
    assert view["overridden"] is True
    assert view["default_tools"] == CHOTU_TOOLS, (
        "the default must survive the change, or reset is unanswerable")


def test_stripping_every_tool_is_respected_and_is_not_untouched(chotu):
    """`None` and `[]` mean different things and must stay distinguishable."""
    from lodestone.agents.presets import get_agent

    get_tool_overrides().set(chotu.id, [])
    assert get_agent(chotu.id).tools == []
    assert grants.for_agent(chotu.id)["overridden"] is True


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
def test_where_an_agent_came_from_is_reported(chotu):
    """`custom` is about whether deleting it makes sense — not whether it can
    be changed, because everything can."""
    assert grants.for_agent("chief-of-staff")["custom"] is False
    assert grants.for_agent(chotu.id)["custom"] is True


def test_every_preset_already_reaches_connectors(notion):
    """Which is why the reported bug could only be a custom agent."""
    for agent in PRESETS.values():
        assert grants.reaches_connectors(agent), f"{agent.id} cannot"


# ── a name is kept even when the catalogue cannot resolve it ─────────────
def test_a_signed_out_connectors_tools_are_not_stripped_from_an_agent(chotu, monkeypatch):
    """Validating a saved list against the live catalogue would turn a Notion
    outage into a permanent edit. `build_tools()` already ignores what it
    cannot find, which is where that belongs."""
    from lodestone.agents.presets import get_agent

    get_tool_overrides().set(chotu.id, ["search_brain", "notion_search"])
    monkeypatch.setattr(mcp_tools, "_supplier", lambda: None)   # Notion goes down
    mcp_tools.clear_cache()

    assert "notion_search" in get_agent(chotu.id).tools, (
        "a temporary outage removed a tool the user had chosen")


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
    from lodestone.agents.library import add_to_roster

    add_to_roster("chief-of-staff")          # nothing is pre-added any more
    rows = {a["id"]: a for a in _client().get("/api/agents").json()["agents"]}
    assert rows[chotu.id]["reaches_connectors"] is False
    assert rows["chief-of-staff"]["reaches_connectors"] is True


def test_the_read_and_the_write_are_one_resource(chotu, notion):
    """GET and PATCH on the same path, rather than a read here and a write
    somewhere else."""
    client = _client()
    assert client.get(f"/api/agents/{chotu.id}/tools").json()[
        "reaches_connectors"] is False

    r = client.patch(f"/api/agents/{chotu.id}/tools",
                     json={"tools": [*CHOTU_TOOLS, SENTINEL]})
    assert r.status_code == 200, r.text
    assert SENTINEL in r.json()["tools"]

    assert client.get(f"/api/agents/{chotu.id}/tools").json()[
        "reaches_connectors"] is True


def test_a_preset_can_be_changed_over_http_too(notion):
    client = _client()
    try:
        r = client.patch("/api/agents/research/tools",
                         json={"tools": ["search_brain"]})
        assert r.status_code == 200, r.text
        assert r.json()["tools"] == ["search_brain"]
        # The shipped constant is untouched — that is what an override buys.
        assert len(PRESETS["research"].tools) > 1
    finally:
        get_tool_overrides().clear("research")


def test_changing_an_agent_that_does_not_exist_is_a_404():
    r = _client().patch("/api/agents/nobody/tools", json={"tools": []})
    assert r.status_code == 404


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


def test_deleting_an_agent_does_not_leave_its_tool_list_behind():
    """An id is a slug of the name, so it repeats. An override left behind
    would apply to an agent that never had it."""
    from lodestone.agents.presets import get_agent

    store = get_custom_store()
    first = store.create("Recycled Name", tools=["search_brain"])
    get_tool_overrides().set(first.id, ["web_search"])
    assert get_agent(first.id).tools == ["web_search"]
    store.delete(first.id)

    second = store.create("Recycled Name", tools=["search_brain"])
    try:
        assert second.id == first.id, "the premise — slugs repeat"
        assert get_agent(second.id).tools == ["search_brain"], (
            "a new agent inherited a deleted agent's tool list")
    finally:
        store.delete(second.id)
