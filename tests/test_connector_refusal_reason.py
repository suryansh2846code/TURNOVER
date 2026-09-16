"""When a connector says no, it usually says why — and that was thrown away.

A user asked an agent to delete a Notion page. It failed with "Notion could not
complete that action." and nothing else. Notion HAD said what was wrong, in the
error result's content; the handler replaced it with a flat sentence. So the
user could not act on it, and neither could the agent — the best it could do was
guess at the argument shape and ask them to paste the error back in.
"""
from __future__ import annotations

from types import SimpleNamespace

from chitragupta.connectors.mcp_source import MAX_REFUSAL_CHARS, _refusal


def _answer(*texts):
    return SimpleNamespace(
        is_error=True,
        content=[SimpleNamespace(text=t) for t in texts])


def test_the_connectors_own_words_reach_the_user():
    said = "body.in_trash should be defined, instead was `undefined`."
    out = _refusal(_answer(said), "Notion")
    assert said in out, "the reason was dropped"
    assert out.startswith("Notion"), "it does not say who refused"


def test_several_blocks_are_joined():
    out = _refusal(_answer("Could not find page.", "Check the ID."), "Notion")
    assert "Could not find page." in out and "Check the ID." in out


def test_a_server_that_says_nothing_still_gets_a_sentence():
    """An empty quotation is worse than a plain statement."""
    for empty in (_answer(), _answer(""), SimpleNamespace(is_error=True, content=None)):
        out = _refusal(empty, "Notion")
        assert out == "Notion could not complete that action."


def test_a_wall_of_text_is_cut_rather_than_becoming_the_card():
    out = _refusal(_answer("x" * 5000), "Notion")
    assert len(out) < MAX_REFUSAL_CHARS + 60
    assert out.endswith("…")


def test_the_reason_travels_all_the_way_to_the_action_result(monkeypatch):
    """End to end: what perform() returns is what the card shows."""
    from chitragupta.connectors import mcp_source

    spec = SimpleNamespace(id="notion", name="Notion", is_remote=True,
                           url="https://example.test/mcp", command="",
                           permits=lambda tool: True, missing_env=list,
                           sync_tool="")
    conn = mcp_source.MCPConnector.__new__(mcp_source.MCPConnector)
    conn.spec, conn.label, conn.name = spec, "Notion", "mcp:notion"

    monkeypatch.setattr(mcp_source, "converse",
                        lambda *a, **k: ("ok", _answer("page_id is not a valid UUID")))

    out = conn.perform("notion-update-page", {"page_id": "nope"}, confirmed=True)

    assert out["ok"] is False
    assert "page_id is not a valid UUID" in out["error"], (
        "the user is still told only that it did not work")


# ── a tool that is not there ─────────────────────────────────────────────
def test_a_missing_tool_names_what_the_connector_can_do_instead(monkeypatch):
    """"Notion has no `x` to run." reads as a glitch. It is a limit, and an
    agent that learns the limit can tell the user instead of guessing at a
    different spelling of the same wrong call."""
    from chitragupta.connectors import mcp_source

    monkeypatch.setattr(
        mcp_source, "probe",
        lambda spec, **kw: (SimpleNamespace(
            readable=["notion-search", "notion-fetch"],
            write=["notion-update-page", "notion-move-pages", "notion-create-pages"],
        ), ""))

    out = mcp_source._no_such_tool(SimpleNamespace(id="notion"), "Notion",
                                   "notion-delete-page")
    assert "no `notion-delete-page`" in out
    assert "not something this connector can do" in out
    assert "notion-update-page" in out, "it did not say what IS there"


def test_it_prefers_tools_that_look_related(monkeypatch):
    from chitragupta.connectors import mcp_source

    monkeypatch.setattr(
        mcp_source, "probe",
        lambda spec, **kw: (SimpleNamespace(
            readable=["notion-search"],
            write=["notion-update-page", "notion-duplicate-page", "notion-create-database"],
        ), ""))
    out = mcp_source._no_such_tool(SimpleNamespace(id="notion"), "Notion",
                                   "notion-archive-page")
    assert "notion-update-page" in out and "notion-duplicate-page" in out


def test_a_connector_that_answers_nothing_still_gets_a_sentence(monkeypatch):
    from chitragupta.connectors import mcp_source

    monkeypatch.setattr(mcp_source, "probe", lambda spec, **kw: (None, "down"))
    out = mcp_source._no_such_tool(SimpleNamespace(id="x"), "Thing", "t")
    assert "does not offer anything like it" in out
