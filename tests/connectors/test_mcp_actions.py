"""Writes happen only after the user has seen and approved them.

Connectors have been read-only by design since decision C1. This is the first
path that changes something in the user's account, so the gate is the point of
the feature rather than a wrapper around it — and it fails **closed**: a caller
that forgets to pass confirmation gets a refusal, not an action.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.connectors.mcp_source import MCPConnector, MCPServerSpec, upsert_server

SERVER = str(Path(__file__).parent / "fake_mcp_server.py")
client = TestClient(app)


def spec_for(mode: str, **over) -> MCPServerSpec:
    return MCPServerSpec(id=over.pop("id", mode), name=f"{mode.title()} Source",
                         command=sys.executable, args=[SERVER, mode], **over)


# ── 4.1 — the gate ─────────────────────────────────────────────────────────


def test_an_unconfirmed_write_is_refused():
    conn = MCPConnector(spec_for("writes"))

    out = conn.perform("delete_record", {"record_id": "1"})

    assert out["ok"] is False
    assert "confirm" in out["error"].lower()


def test_confirmation_is_required_explicitly_not_by_default():
    """`confirmed` defaults to False, so a caller that forgets it fails closed.

    Getting this backwards means every future call site is one missing keyword
    away from changing the user's account without asking.
    """
    import inspect

    signature = inspect.signature(MCPConnector.perform)

    assert signature.parameters["confirmed"].default is False
    assert signature.parameters["confirmed"].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_confirmed_write_runs():
    conn = MCPConnector(spec_for("writes"))

    out = conn.perform("delete_record", {"record_id": "7"}, confirmed=True)

    assert out["ok"] is True
    assert "7" in str(out["detail"])


def test_a_write_outside_the_allow_list_is_refused_even_when_confirmed():
    """Confirmation approves *an* action; it does not widen what the connector
    was permitted to do in the first place."""
    conn = MCPConnector(spec_for("writes", allowed_tools=["list_records"]))

    out = conn.perform("delete_record", {"record_id": "1"}, confirmed=True)

    assert out["ok"] is False
    assert "not allowed" in out["error"]


def test_a_tool_the_server_does_not_have_is_refused():
    conn = MCPConnector(spec_for("writes"))

    out = conn.perform("launch_missiles", {}, confirmed=True)

    assert out["ok"] is False
    assert "no `launch_missiles`" in out["error"]


def test_a_failing_action_explains_itself():
    conn = MCPConnector(spec_for("crash"))

    out = conn.perform("anything", {}, confirmed=True)

    assert out["ok"] is False
    assert "Traceback" not in out["error"]
    assert "vendor database" not in out["error"], "raw stderr reached the user"


# ── 4.2 — the user can see what would change ───────────────────────────────


def test_actions_are_listed_without_being_run():
    """The list a confirmation card is built from. Asking for it must not
    change anything — that is the whole difference between showing and doing."""
    conn = MCPConnector(spec_for("writes"))

    actions = conn.available_actions()

    names = {a["tool"] for a in actions}
    assert names == {"delete_record", "send_message"}
    assert all(a["label"] == "Writes Source" for a in actions)


def test_a_read_only_connector_offers_no_actions():
    assert MCPConnector(spec_for("listing")).available_actions() == []


def test_the_allow_list_narrows_what_is_offered():
    conn = MCPConnector(spec_for("writes", allowed_tools=["send_message"]))

    assert [a["tool"] for a in conn.available_actions()] == ["send_message"]


def test_a_sync_never_calls_a_write(poison):
    """The guarantee underneath all of this: routine background work must not
    be able to reach an action, confirmed or otherwise."""
    called: list[str] = []
    conn = MCPConnector(spec_for("writes"))
    real = MCPConnector.perform
    MCPConnector.perform = lambda self, tool, *a, **k: called.append(tool)
    try:
        conn.sync(interactive=False)
    finally:
        MCPConnector.perform = real

    assert called == []


# ── the HTTP surface ───────────────────────────────────────────────────────


def test_the_endpoint_refuses_an_unconfirmed_action():
    upsert_server(spec_for("writes", id="http"))

    resp = client.post("/api/connectors/mcp/http/action",
                       json={"tool": "delete_record", "arguments": {"record_id": "1"}})

    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "confirm" in resp.json()["error"].lower()


def test_the_endpoint_runs_a_confirmed_action():
    upsert_server(spec_for("writes", id="http"))

    resp = client.post("/api/connectors/mcp/http/action",
                       json={"tool": "send_message", "confirmed": True,
                             "arguments": {"to": "dev", "body": "ship it"}})

    assert resp.json()["ok"] is True


def test_the_endpoint_lists_actions():
    upsert_server(spec_for("writes", id="http"))

    resp = client.get("/api/connectors/mcp/http/actions")

    assert {a["tool"] for a in resp.json()["actions"]} == {"delete_record",
                                                          "send_message"}


def test_an_unknown_connector_is_a_clean_404():
    resp = client.post("/api/connectors/mcp/never-set-up/action",
                       json={"tool": "x", "confirmed": True})

    assert resp.status_code == 404
    assert "not set up" in resp.json()["detail"]
