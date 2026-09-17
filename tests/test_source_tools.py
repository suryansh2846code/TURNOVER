"""Eleven connectors are registered; one of them used to have a tool.

So Personal — described to the user as a chief of staff — had no way to look at
a calendar, and no agent could refresh a stale source. And gmail_search ran one
string through both a Gmail fetch and an embedding index, so its own default,
`newer_than:30d`, reached semantic recall as a query meaning nothing at all.
"""
from __future__ import annotations

from chitragupta.agents import source_tools
from chitragupta.agents.presets import PRESETS
from chitragupta.agents.tools import TOOL_DEFS, TOOL_IMPLS, build_tools, run_tool


# ── calendar ─────────────────────────────────────────────────────────────
def test_the_agents_that_run_your_day_can_look_at_a_calendar():
    """The omission that made "chief of staff" a claim we could not keep.

    Not every agent: a researcher has no business in the diary. What matters is
    that the ones whose job is the user's day can see it.
    """
    for agent_id in ("chief-of-staff", "inbox", "personal"):
        agent = PRESETS[agent_id]
        names = {t.name for t in build_tools(agent.tools, self_id=agent.id)}
        assert "calendar_lookup" in names, f"{agent_id} cannot see the calendar"


def test_calendar_lookup_understands_the_periods_people_say():
    for phrase in ("today", "tomorrow", "this week", "2026-09-15"):
        out = run_tool("calendar_lookup", {"when": phrase})
        assert out.ok, f"{phrase!r} was rejected: {out}"


def test_an_unreadable_period_is_a_failure_that_says_what_to_do():
    out = run_tool("calendar_lookup", {"when": "whenever-ish"})
    assert not out.ok
    assert "today" in out and "tomorrow" in out


def test_with_no_calendar_connected_it_says_so_rather_than_being_empty(monkeypatch):
    monkeypatch.setattr(source_tools, "_configured", lambda name: (False, "no account"))
    monkeypatch.setattr(source_tools, "MAX_EVENTS", 5)
    out = run_tool("calendar_lookup", {"when": "today"})
    assert out.ok
    assert "Connectors panel" in out, out


# ── refreshing ───────────────────────────────────────────────────────────
def test_sync_source_names_the_sources_it_knows():
    out = run_tool("sync_source", {"source": ""})
    assert not out.ok
    assert "gmail" in out and "notion" in out


def test_refreshing_something_that_is_not_connected_explains_itself(monkeypatch):
    """Not machine-dependent: the point is the shape of the answer, not whether
    this particular laptop happens to have Gmail linked."""
    monkeypatch.setattr(source_tools, "_configured",
                        lambda name: (False, "no Google account is linked"))
    out = run_tool("sync_source", {"source": "gmail"})
    assert not out.ok
    assert "not connected" in out
    assert "Connectors panel" in out, "the failure does not say what to do next"


def test_a_sync_in_a_turn_never_opens_a_browser(monkeypatch):
    """A tool call must not stop and wait for someone looking at a chat window."""
    seen = {}

    class _Conn:
        def is_configured(self):
            return True, ""

        def sync(self, **kw):
            seen.update(kw)
            class R:
                errors: list = []
                added = 3
            return R()

    monkeypatch.setattr(source_tools, "_connector", lambda name: _Conn())
    monkeypatch.setattr(source_tools, "_configured", lambda name: (True, ""))
    out = run_tool("sync_source", {"source": "gmail"})
    assert out.ok
    assert seen.get("interactive") is False, "a mid-turn sync could open a browser"
    assert "3 new" in out


# ── searching a source ───────────────────────────────────────────────────
def test_search_source_keeps_the_filter_out_of_the_semantic_query(monkeypatch):
    """The bug gmail_search had: source syntax fed to an embedding index."""
    sent = {}

    class _Conn:
        def is_configured(self):
            return True, ""

        def sync(self, **kw):
            sent["fetch_query"] = kw.get("query")
            class R:
                errors: list = []
                added = 0
            return R()

    monkeypatch.setattr(source_tools, "_connector", lambda name: _Conn())
    monkeypatch.setattr(source_tools, "_configured", lambda name: (True, ""))

    class _Brain:
        def recall(self, query, **kw):
            sent["recall_query"] = query
            return {"context": "some mail"}

    monkeypatch.setattr(source_tools, "get_brain", lambda: _Brain())

    run_tool("search_source", {"source": "gmail", "about": "the invoice from Dana",
                               "filter": "from:dana newer_than:7d"})

    assert sent["fetch_query"] == "from:dana newer_than:7d"
    assert sent["recall_query"] == "the invoice from Dana"
    assert "newer_than" not in sent["recall_query"], (
        "source query syntax reached the semantic index again")


def test_search_source_insists_on_words_not_syntax():
    out = run_tool("search_source", {"source": "gmail", "about": ""})
    assert not out.ok
    assert "filter" in out


# ── wiring ───────────────────────────────────────────────────────────────
def test_every_new_tool_is_declared_and_implemented():
    for name in ("calendar_lookup", "sync_source", "search_source"):
        assert name in TOOL_DEFS and name in TOOL_IMPLS
