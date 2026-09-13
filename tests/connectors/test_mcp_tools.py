"""The agent-facing surface: what a model may call on a configured server.

Same rule as the rest of this suite — every test here spawns a real server as a
real subprocess and speaks the real protocol to it. The three properties the
agent loop depends on and a sync does not are each pinned by a test that fails
loudly if it is lost: asking is cheap, writes are unreachable, and a broken
server costs a sentence rather than the turn.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lodestone.connectors import mcp_source, mcp_tools
from lodestone.connectors.mcp_source import MCPServerSpec, upsert_server
from lodestone.connectors.mcp_tools import (
    MCPToolRef,
    call_tool,
    invalidate,
    list_tools,
)

SERVER = str(Path(__file__).parent / "fake_mcp_server.py")


def spec_for(mode: str, **over) -> MCPServerSpec:
    return MCPServerSpec(
        id=over.pop("id", mode), name=over.pop("name", f"{mode.title()} Source"),
        command=sys.executable, args=[SERVER, mode], **over)


@pytest.fixture(autouse=True)
def fresh_cache():
    """The tool cache outlives a test; the home directory does not.

    `isolated_home` gives every test its own `mcp_servers.json`, so without this
    the second test in the file would be answered from the first test's cache —
    against servers whose spec file no longer exists. That is the same failure
    the home fixture's docstring describes, one layer up.
    """
    invalidate()
    yield
    invalidate()


@pytest.fixture
def spawns(monkeypatch):
    """Count real subprocess launches.

    `_converse` is the only place a server process is started, so counting calls
    to it counts spawns exactly — and counting the public wrapper instead would
    have let a cache that re-listed on every hit pass.
    """
    class Counter:
        count = 0

    real = mcp_source._converse

    async def counting(spec, action):
        Counter.count += 1
        return await real(spec, action)

    monkeypatch.setattr(mcp_source, "_converse", counting)
    return Counter


# ── asking what exists must be cheap ───────────────────────────────────────


def test_the_second_call_spawns_no_subprocess(spawns):
    """The constraint this module exists for.

    `probe()` launches a process per server and the agent loop asks on every
    turn. Uncached, a user with four connectors pays four spawns per message,
    which is the Models-drawer freeze moved inside chat.
    """
    upsert_server(spec_for("listing"))

    first = list_tools()
    after_first = spawns.count
    second = list_tools()

    assert first and after_first == 1
    assert spawns.count == after_first, "the cached call started a server again"
    assert second == first


def test_adding_a_server_is_visible_immediately(spawns):
    """A TTL that outlives a change is a lie the user can see."""
    upsert_server(spec_for("listing"))
    assert [r.tool for r in list_tools()] == ["list_records"]

    upsert_server(spec_for("search"))

    assert "search_records" in {r.tool for r in list_tools()}


def test_removing_a_server_takes_its_tools_with_it():
    upsert_server(spec_for("listing"))
    assert list_tools()

    mcp_source.delete_server("listing")

    assert list_tools() == []


def test_invalidate_forces_a_fresh_look(spawns):
    upsert_server(spec_for("listing"))
    list_tools()
    before = spawns.count

    invalidate()
    list_tools()

    assert spawns.count == before + 1


# ── what a tool looks like to a model ──────────────────────────────────────


def test_a_tool_carries_everything_a_model_needs():
    upsert_server(spec_for("search"))

    ref = list_tools()[0]

    assert isinstance(ref, MCPToolRef)
    assert ref.qualified_name == "mcp__search__search_records"
    assert ref.server_id == "search" and ref.server_label == "Search Source"
    assert ref.tool == "search_records"
    assert "query" in ref.description.lower() or ref.description
    assert ref.parameters["properties"]["query"]
    assert ref.writes is False


def test_qualified_names_are_legal_and_unique():
    """Providers constrain tool names (`^[a-zA-Z0-9_-]{1,64}$`), and a name
    that is rejected at send time is a tool the user paid to discover and can
    never use."""
    import re

    upsert_server(spec_for("listing", id="a source/with spaces"))
    upsert_server(spec_for("writes", id="x" * 90))

    names = [r.qualified_name for r in list_tools()]

    assert len(names) == len(set(names))
    for name in names:
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name), name


def test_a_search_only_server_is_still_useful_here():
    """The whole point of this surface.

    `classify_tools()` refuses to sync a server that can only search — it cannot
    enumerate, so syncing it would invent a brain rather than fill one. It can
    still answer a question the user just asked, and until this module there was
    no way for the model to ask.
    """
    upsert_server(spec_for("search"))

    out = call_tool("mcp__search__search_records", {"query": "launch"})

    assert "Launch checklist" in out


def test_a_disallowed_tool_is_not_offered_at_all():
    """Least privilege is about what can be reached. Listing a tool the model
    may not call is only an invitation to try it."""
    upsert_server(spec_for("writes", allowed_tools=["list_records"]))

    names = {r.tool for r in list_tools()}

    assert names == {"list_records"}


# ── reads only ─────────────────────────────────────────────────────────────


def test_a_write_tool_is_never_callable():
    """Writes keep the propose/confirm path. `mcp_action` is in
    `NEVER_UNATTENDED` because the text an agent reasons about is text a
    stranger wrote; widening this is how an email's `<action>` becomes a
    deletion."""
    upsert_server(spec_for("writes"))

    delete = next(r for r in list_tools() if r.tool == "delete_record")
    out = call_tool(delete.qualified_name, {"record_id": "1"})

    assert delete.writes is True
    assert "approve" in out.lower()
    assert "deleted" not in out.lower(), "a write ran from the read surface"


def test_every_write_the_server_declares_is_flagged():
    upsert_server(spec_for("writes"))

    flagged = {r.tool for r in list_tools() if r.writes}

    assert flagged == {"delete_record", "send_message"}


def test_an_unknown_name_is_refused_without_starting_anything(spawns):
    upsert_server(spec_for("listing"))
    list_tools()
    before = spawns.count

    out = call_tool("mcp__listing__drop_everything", {})

    assert "no connector tool" in out.lower()
    assert spawns.count == before, "a refusal still launched a server"


def test_a_tool_the_user_has_since_disallowed_is_refused():
    """The cache is a convenience, never the authority — `call_tool` re-reads
    the saved spec, so a permission narrowed a second ago is already in force."""
    upsert_server(spec_for("listing"))
    ref = list_tools()[0]

    mcp_source._save({"listing": {**spec_for("listing").as_dict(),
                                  "allowed_tools": ["something_else"]}})
    out = call_tool(ref.qualified_name, {})

    assert "not allowed" in out.lower()


def test_a_server_removed_mid_turn_says_so():
    upsert_server(spec_for("listing"))
    ref = list_tools()[0]

    mcp_source._save({})
    out = call_tool(ref.qualified_name, {})

    assert "no longer connected" in out.lower()


# ── failures cost a sentence, never the turn ───────────────────────────────


def test_a_server_that_is_down_degrades_to_a_message():
    upsert_server(spec_for("crash"))
    upsert_server(MCPServerSpec(id="gone", name="Ghost Source",
                                command="/nonexistent/definitely-not-here"))

    tools = list_tools()

    assert tools == [], "a server that will not start contributed tools"


def test_one_broken_server_does_not_remove_the_others():
    """Same class of bug as a sync aborting on one bad item: a user with four
    connectors must not lose all four to one uninstalled binary."""
    upsert_server(spec_for("crash"))
    upsert_server(spec_for("listing"))

    assert [r.tool for r in list_tools()] == ["list_records"]


def test_a_call_to_a_broken_server_explains_itself():
    upsert_server(spec_for("listing"))
    ref = list_tools()[0]
    mcp_source._save({"listing": {**spec_for("listing").as_dict(),
                                  "command": "/nonexistent/nope"}})

    out = call_tool(ref.qualified_name, {})

    assert "Traceback" not in out and "Error" not in out
    assert "Listing Source" in out


def test_stalled_servers_are_asked_at_the_same_time(monkeypatch):
    """N servers must cost one timeout, not N of them.

    Asked one after another, a user with three connectors and two dead ones
    waits out both ceilings before the working one is even started — which is
    the freeze this module exists to avoid, not a smaller version of it.
    """
    import time

    monkeypatch.setattr(mcp_source, "LIST_TIMEOUT_SECONDS", 2.0)
    upsert_server(spec_for("stall", id="stall-one"))
    upsert_server(spec_for("stall", id="stall-two"))
    upsert_server(spec_for("listing"))

    started = time.monotonic()
    tools = list_tools()
    elapsed = time.monotonic() - started

    assert [r.tool for r in tools] == ["list_records"]
    assert elapsed < 6.0, f"the stalled servers were asked in turn ({elapsed:.1f}s)"


def test_a_hanging_server_does_not_hold_the_turn(monkeypatch):
    """A model turn the user is watching cannot wait on a subprocess that will
    never answer. The ceiling covers the whole conversation, because a server
    that hangs while *starting* never reaches the call at all."""
    monkeypatch.setattr(mcp_tools, "TURN_TIMEOUT_SECONDS", 2.0)
    upsert_server(spec_for("hang"))

    out = call_tool("mcp__hang__list_records", {})

    assert "too long" in out.lower()
    assert "Hang Source" in out


def test_a_failure_never_carries_an_internal():
    upsert_server(MCPServerSpec(id="secretive", name="Secretive Source",
                                command="/nonexistent/nope"))
    invalidate()
    out = call_tool("mcp__secretive__anything", {})

    assert "nonexistent" not in out
    assert "Traceback" not in out


# ── the reply is something a model can actually hold ───────────────────────


def test_a_huge_reply_is_truncated_and_says_so():
    """A tool answering with its vendor's raw JSON can return megabytes, and one
    such reply would evict the conversation, the recall block and the system
    prompt before the model ever read it."""
    upsert_server(spec_for("huge"))

    out = call_tool("mcp__huge__read_everything", {})

    assert len(out) < mcp_tools.MAX_RESULT_CHARS + 400
    assert "Truncated" in out, "the model was not told it saw a fraction"
    assert "200,000" in out


def test_records_come_back_as_readable_text():
    upsert_server(spec_for("listing"))

    out = call_tool("mcp__listing__list_records", {})

    assert "Quarterly planning" in out and "Hiring loop" in out


def test_prose_stays_prose():
    """It is what the user would have read; re-encoding it as JSON only spends
    tokens on quotes and escapes."""
    upsert_server(spec_for("prose"))

    out = call_tool("mcp__prose__list_notes", {})

    assert out.startswith("Quarterly planning:")
    assert "\\n" not in out
