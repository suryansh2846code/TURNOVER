"""Edge-case regression tests — hardening pass.

Each test here pins a bug found (and fixed) during the hardening sweep, so it
can never silently regress. Grouped by module.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from lodestone.actions import parse_actions
from lodestone.connectors.apple_calendar import _fmt_dt, parse_ics
from lodestone.connectors.custom_api import _dig
from lodestone.core.chunk import chunk_text
from lodestone.reminders import parse_when

NOW = datetime(2026, 8, 30, 13, 0, 0).astimezone()


# ── parse_when: invalid times must return None, never crash ────────────────
@pytest.mark.parametrize("bad", ["3:70", "9:99", "99:99", "9:99am", "25pm", "30pm"])
def test_parse_when_invalid_time_returns_none(bad):
    assert parse_when(bad, NOW) is None          # was: ValueError crash


@pytest.mark.parametrize("text,hhmm", [
    ("12am", "00:00"), ("12pm", "12:00"), ("noon", "12:00"),
    ("midnight", "00:00"), ("tomorrow 3pm", "15:00"),
    ("2026-09-01 15:30", "15:30"),
])
def test_parse_when_valid_times(text, hhmm):
    out = parse_when(text, NOW)
    assert out is not None and out[11:16] == hhmm


def test_parse_when_relative_offset():
    assert parse_when("in 90 minutes", NOW).startswith("2026-08-30T14:30")


@pytest.mark.parametrize("empty", ["", "   ", "blah", "monday 9"])
def test_parse_when_unparseable(empty):
    assert parse_when(empty, NOW) is None


# ── parse_actions: never crash on malformed model output ───────────────────
@pytest.mark.parametrize("text", [
    "", "<action type='x'>y</action>", "<action foo=bar>y",
    "<action type=set_reminder at=3pm>x</action>",   # unquoted → ignored
])
def test_parse_actions_malformed_no_crash(text):
    assert isinstance(parse_actions(text), list)


def test_parse_actions_extracts_multiple():
    text = ('<action type="set_reminder" at="3pm">a</action> and '
            '<action type="send_email" to="x@y.z">b</action>')
    acts = parse_actions(text)
    assert [a["type"] for a in acts] == ["set_reminder", "send_email"]
    assert acts[0]["params"]["message"] == "a"
    assert acts[1]["params"]["to"] == "x@y.z"


def test_parse_actions_multiline_body():
    acts = parse_actions('<action type="send_email" to="x@y.z">\nl1\nl2\n</action>')
    assert acts[0]["params"]["body"] == "l1\nl2"


# ── _dig: dot-path extraction is crash-proof ───────────────────────────────
@pytest.mark.parametrize("obj,path,exp", [
    ({"a": {"b": 9}}, "a.b", 9),
    ({"a": 1}, "a.b.c", None),
    (None, "x", None),
    ({"a": None}, "a.b", None),
    ({"a": {"b": [1, 2]}}, "a.b", [1, 2]),
    ({"x": 1}, "", {"x": 1}),
])
def test_dig(obj, path, exp):
    assert _dig(obj, path) == exp


# ── connector parsers: junk in, no crash ───────────────────────────────────
@pytest.mark.parametrize("raw", ["garbage", "", "2026", "20260901", "20260901T150000Z"])
def test_fmt_dt_no_crash(raw):
    assert isinstance(_fmt_dt(raw), str)


@pytest.mark.parametrize("txt", ["", "not an ics", "DTSTART:x\nSUMMARY:"])
def test_parse_ics_bad_returns_none(txt):
    assert parse_ics(txt) is None


def test_parse_ics_minimal():
    ev = parse_ics("SUMMARY:Standup\nDTSTART:20260901T090000Z")
    assert ev and ev["summary"] == "Standup" and ev["start"].startswith("2026-09-01")


# ── chunk_text: boundaries ─────────────────────────────────────────────────
@pytest.mark.parametrize("text,expect_empty", [("", True), ("   ", True), ("x" * 5000, False)])
def test_chunk_text_bounds(text, expect_empty):
    chunks = chunk_text(text)
    assert (len(chunks) == 0) == expect_empty
    assert all(len(c) <= 1200 for c in chunks)


# ── connectors: every registered connector instantiates + reports readiness ─
def test_all_connectors_instantiate():
    from lodestone.connectors import REGISTRY
    for name, cls in REGISTRY.items():
        inst = cls()
        ready, reason = inst.is_configured()
        assert isinstance(ready, bool)
        assert isinstance(reason, str)


# ── custom apps: storage round-trip (create → get → delete), no network ─────
def test_custom_app_storage_roundtrip():
    from lodestone.connectors.custom_api import upsert_app, get_app, delete_app
    app = upsert_app({"name": "T", "base_url": "https://ex.com", "endpoint": "/x"},
                     token="secret123")
    aid = app["id"]
    try:
        assert get_app(aid)["base_url"] == "https://ex.com"
        # addressed as custom:<id> through the connector factory
        from lodestone.connectors import get_connector
        conn = get_connector(f"custom:{aid}")
        assert conn.label == "T"
    finally:
        assert delete_app(aid) is True
        assert get_app(aid) is None


def test_custom_api_fieldless_records_stay_distinct(tmp_path, monkeypatch):
    """Records missing the title/body field must not collapse to one 'None'."""
    monkeypatch.setenv("LODESTONE_HOME", str(tmp_path))
    from lodestone.config import get_settings
    get_settings.cache_clear()
    from lodestone.connectors.custom_api import CustomAPIConnector
    app = {"id": "z", "name": "T", "base_url": "https://ex.com", "endpoint": "/x",
           "auth_type": "none", "items_path": "d", "title_field": "name",
           "body_field": "desc"}
    conn = CustomAPIConnector(dict(app))
    conn._request = lambda: {"d": [{"other": 1}, {"other": 2}, {"other": 3}]}
    res = conn.sync()
    assert res.added == 3 and res.skipped == 0
    get_settings.cache_clear()


# ── reminders/scheduler: fire once, never double-fire ──────────────────────
def test_reminder_fires_once(tmp_path, monkeypatch):
    monkeypatch.setenv("LODESTONE_HOME", str(tmp_path))
    from lodestone.config import get_settings
    get_settings.cache_clear()
    import lodestone.notify as notify
    calls = []
    monkeypatch.setattr(notify, "desktop_notify", lambda t, m: calls.append((t, m)) or True)

    from datetime import datetime, timedelta
    import lodestone.reminders as reminders_mod
    from lodestone.reminders import get_reminders
    from lodestone.scheduler import Scheduler
    monkeypatch.setattr(reminders_mod, "_store", None)   # rebind to tmp home
    store = get_reminders()
    past = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat()
    future = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
    store.add("past task", past)
    store.add("future task", future)

    sched = Scheduler()
    sched._fire_reminders()
    assert [m for _, m in calls] == ["past task"]      # only the due one
    assert store.due() == []                            # marked fired
    sched._fire_reminders()
    assert [m for _, m in calls] == ["past task"]      # no double-notify
    monkeypatch.setattr(reminders_mod, "_store", None)
    get_settings.cache_clear()


# ── migrations: idempotent, version-bump triggered, empty-safe ─────────────
def test_migrations_idempotent_and_bump_triggered(tmp_path, monkeypatch):
    monkeypatch.setenv("LODESTONE_HOME", str(tmp_path))
    from lodestone.config import get_settings
    from lodestone.brain import get_brain
    from lodestone.core.store import get_store
    get_settings.cache_clear()
    get_brain.cache_clear()
    get_store.cache_clear()

    brain = get_brain()
    assert brain.run_migrations() == {}                 # empty brain: safe no-op
    brain.ingest("Alpha ships in September.", source="test")
    assert brain.run_migrations()                        # first run does work
    assert brain.run_migrations() == {}                  # idempotent

    brain.store.set_meta("embedder_sig", "STALE")
    assert brain.run_migrations().get("reembedded", 0) > 0
    assert brain.run_migrations() == {}                  # re-stamped → no-op

    brain.store.set_meta("extractor_version", "0")
    assert "graph_rebuilt" in brain.run_migrations()

    get_settings.cache_clear()
    get_brain.cache_clear()
    get_store.cache_clear()
