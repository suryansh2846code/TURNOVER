"""The MCP-backed connector, driven against real servers over real stdio.

Every test here spawns `fake_mcp_server.py` as an actual subprocess and speaks
the actual protocol to it. A stubbed session would test the stub, and the whole
risk in this phase is the handshake, the transport, and the shapes real servers
answer with.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lodestone.connectors.mcp_source import (
    MCPConnector,
    MCPServerSpec,
    classify_tools,
    delete_server,
    get_server,
    list_servers,
    probe,
    upsert_server,
)

SERVER = str(Path(__file__).parent / "fake_mcp_server.py")


def spec_for(mode: str, **over) -> MCPServerSpec:
    return MCPServerSpec(
        id=over.pop("id", mode), name=over.pop("name", f"{mode.title()} Source"),
        command=sys.executable, args=[SERVER, mode], **over)


# ── 2.1 — it talks to a real server ────────────────────────────────────────


def test_a_listing_server_is_synced_end_to_end():
    from lodestone.core.store import get_store

    conn = MCPConnector(spec_for("listing"))
    result = conn.sync(interactive=False)

    assert not result.errors, result.errors
    assert result.added == 3
    stored = get_store().list(source=conn.name, limit=10)
    assert len(stored) == 3
    assert any("connector layer" in m.text for m in stored)


def test_records_keep_their_titles():
    from lodestone.core.store import get_store

    MCPConnector(spec_for("listing")).sync(interactive=False)

    titles = {m.title for m in get_store().list(source="mcp:listing", limit=10)}
    assert "Quarterly planning" in titles


@pytest.mark.parametrize("mode,expected", [("text", 3), ("prose", 1)])
def test_other_answer_shapes_are_read(mode, expected):
    """Servers answer in three shapes and all three are common: structured
    JSON, a JSON document inside a text block, and plain prose. Prose is still
    worth keeping — it is what the user would have read."""
    result = MCPConnector(spec_for(mode)).sync(interactive=False)

    assert not result.errors, result.errors
    assert result.added == expected


# ── 2.2 — a search-only server must say so, not sync nothing ───────────────


def test_a_search_only_server_is_not_synced():
    """The honest failure mode of this whole phase.

    A server exposing only `search_records` cannot enumerate, and calling it
    with an invented query would fabricate a brain rather than fill one. What
    it must not do is report success with zero records, which is exactly how a
    user concludes the app is broken.

    **Changed in Phase 6, deliberately.** This used to assert the connector was
    *not configured*. That was right when a search-only server was useless to
    us; Phase 5 made its tools callable inside a turn, so the same server is now
    a working connector and reporting it as unconnected became the dishonest
    answer — most of the remote catalog (Notion among them) exposes search and
    no listing. What must stay true is the original guarantee: it is never
    synced, and never claims to have been. That is now expressed as
    `can_sync=False`, which is also what removes its Sync button.
    """
    conn = MCPConnector(spec_for("search"))

    ready, reason, can_sync = conn.status()

    assert ready, "a server whose tools an agent can call is connected"
    assert not reason
    assert not can_sync, "there is nothing here to pull in ahead of time"


def test_a_search_only_sync_explains_itself():
    result = MCPConnector(spec_for("search")).sync(interactive=False)

    assert result.added == 0
    assert result.errors, "a search-only server reported success with no records"
    assert "search" in result.detail.lower() or "cannot list" in result.detail


def test_classification_uses_arguments_not_names():
    """A required `query` is proof; a name is only a hint.

    Classifying on names alone calls `list_matching(query)` a lister and then
    invents an argument for it.
    """
    class Tool:
        def __init__(self, name, required=(), annotations=None):
            self.name = name
            self.input_schema = {"type": "object", "required": list(required)}
            self.annotations = annotations

    kinds = classify_tools([
        Tool("list_matching", required=["query"]),   # named like a lister, isn't
        Tool("entries"),                             # named like nothing, is
        Tool("list_messages", required=["cursor"]),  # paging only, still a lister
    ])

    assert kinds.bulk == ["entries", "list_messages"]
    assert kinds.query == ["list_matching"]


def test_write_tools_are_never_used_for_a_sync():
    """A connector is read-only until Phase 4 says otherwise, and getting this
    wrong means a sync mutating the user's account."""
    kinds, _ = probe(spec_for("writes"))

    assert "delete_record" in kinds.write
    assert "send_message" in kinds.write
    assert kinds.bulk == ["list_records"], "a write tool leaked into the sync path"


def test_a_server_with_writes_still_syncs_its_reads():
    result = MCPConnector(spec_for("writes")).sync(interactive=False)

    assert not result.errors, result.errors
    assert result.added == 3


# ── 2.4 / 2.5 — failures are explained, never dumped ───────────────────────


def test_a_server_that_crashes_is_not_connected():
    conn = MCPConnector(spec_for("crash"))

    ready, reason = conn.is_configured()

    assert not ready
    assert reason and "Traceback" not in reason
    assert "vendor database" not in reason, "raw stderr reached the user"


def test_a_missing_program_says_what_to_do():
    conn = MCPConnector(MCPServerSpec(
        id="gone", name="Ghost Source",
        command="/nonexistent/definitely-not-here", args=[]))

    ready, reason = conn.is_configured()

    assert not ready
    assert "Ghost Source" in reason
    assert "missing" in reason or "Reinstall" in reason


def test_a_failing_sync_returns_a_result_rather_than_raising():
    """Same rule as `chat()` in the model layer: an uncaught raise here turns a
    connector problem into a 500."""
    result = MCPConnector(spec_for("crash")).sync(interactive=False)

    assert result.connector == "mcp:crash"
    assert result.errors
    assert "Traceback" not in " ".join(result.errors)


def test_an_error_never_carries_an_internal():
    from lodestone.connectors.mcp_errors import explain

    message = explain(RuntimeError("sk-proj-AAAABBBBCCCCDDDDEEEEFFFFGGGG failed"),
                      "Some Source")

    assert "sk-proj" not in message
    assert "RuntimeError" not in message


def test_a_configured_server_reports_ready():
    ready, reason = MCPConnector(spec_for("listing")).is_configured()

    assert ready and reason == ""


# ── the contract the other suites assume ───────────────────────────────────


def test_it_honours_cancel_and_progress():
    import threading

    conn = MCPConnector(spec_for("listing"))
    stopped = threading.Event()
    stopped.set()

    assert conn.sync(interactive=False, cancel=stopped).added == 0

    ticks: list[tuple] = []
    conn.sync(interactive=False, progress=lambda *a: ticks.append(a))
    assert len(ticks) == 3


def test_a_second_sync_stores_nothing_new():
    from lodestone.core.store import get_store

    conn = MCPConnector(spec_for("listing"))
    conn.sync(interactive=False)
    before = get_store().count()

    second = conn.sync(interactive=False)

    assert second.added == 0
    assert get_store().count() == before


def test_one_bad_record_does_not_abort_the_sync(poison):
    conn = MCPConnector(spec_for("listing"))
    breaker = poison(nth=2)

    result = conn.sync(interactive=False)

    assert breaker.raised
    assert result.added >= 2
    assert result.skipped >= 1


# ── the spec store ─────────────────────────────────────────────────────────


def test_servers_round_trip_through_disk():
    upsert_server(spec_for("listing", id="saved", name="Saved Source"))

    assert [s.id for s in list_servers()] == ["saved"]
    assert get_server("saved").name == "Saved Source"
    assert delete_server("saved")
    assert list_servers() == []


def test_get_connector_resolves_an_mcp_name():
    from lodestone.connectors import get_connector

    upsert_server(spec_for("listing", id="wired"))

    conn = get_connector("mcp:wired")

    assert isinstance(conn, MCPConnector)
    assert conn.label == "Listing Source"


def test_an_unknown_mcp_name_is_a_clear_error():
    from lodestone.connectors import get_connector

    with pytest.raises(KeyError):
        get_connector("mcp:never-configured")


def test_the_scheduler_picks_up_configured_servers():
    from lodestone.scheduler import _mcp_servers

    upsert_server(spec_for("listing", id="scheduled"))

    assert _mcp_servers() == ["scheduled"]
