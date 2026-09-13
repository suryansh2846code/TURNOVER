"""Every connector actually ingests what it is given.

This is the baseline the connector layer has never had: run the real `sync()`
against fabricated records and check the memories land. Until now the suite
executed five pure helpers and no `sync()` at all, so a connector could stop
ingesting entirely — a renamed API field, a changed payload shape — and nothing
would fail until a user noticed their brain was empty.
"""
from __future__ import annotations

import pytest

from . import harness
from .harness import FAKES

IDS = [f.name for f in FAKES]


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_sync_ingests_every_record(fake, monkeypatch, fake_module, tmp_path):
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 3)
    result = harness.sync(conn, kwargs)

    assert not result.errors, f"{fake.name} reported errors: {result.errors}"
    assert result.added == fake.expected(3), (
        f"{fake.name} added {result.added}, expected {fake.expected(3)}")


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_sync_writes_memories_that_can_be_recalled(fake, monkeypatch, fake_module,
                                                   tmp_path):
    """Added != stored. A connector that reports success while writing nothing
    is the failure mode the header pill would show as a healthy brain."""
    from lodestone.core.store import get_store

    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 3)
    harness.sync(conn, kwargs)

    stored = get_store().list(source=conn.name, limit=50)
    assert stored, f"{fake.name} wrote no memory under its own source name"


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_sync_records_its_state(fake, monkeypatch, fake_module, tmp_path):
    """`_finish()` must stamp connector_state — it is what the UI reads to show
    "last synced", and a connector that forgets it looks permanently stale."""
    from lodestone.core.store import get_store

    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 2)
    harness.sync(conn, kwargs)

    state = get_store().get_connector_state(conn.name)
    assert state is not None, f"{fake.name} never wrote connector_state"
    assert state.get("last_sync"), f"{fake.name} left last_sync empty"
    assert state.get("status") == "ok"


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_empty_source_is_not_an_error(fake, monkeypatch, fake_module, tmp_path):
    """A source with nothing in it is a normal state, not a failure.

    "Assume nothing is configured" (CLAUDE.md) applies after connecting too: a
    brand-new Notion workspace or an empty inbox must report zero, not red.
    """
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 0)
    if conn.name == "notes":
        kwargs = {"text": ""}        # the empty case for a connector with no source
    result = harness.sync(conn, kwargs)

    assert not result.errors, f"{fake.name} treated an empty source as an error"
