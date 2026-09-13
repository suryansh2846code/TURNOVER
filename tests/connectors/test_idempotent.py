"""Syncing twice must not store the same thing twice.

The background scheduler re-runs every ready connector on a timer, so a
connector's *second* pass is by far its most common one. Duplicates there are
not cosmetic: recall is scored over the whole memory table, so the same email
stored five times outranks five different ones, and the brain gets worse the
longer the app is left running — which is the opposite of the promise.

Today this holds only because of the `idx_memories_chash` unique index. No
connector checks anything. That is a fine mechanism and a fragile guarantee, so
it is frozen here before Phase 1 changes how fetching works.
"""
from __future__ import annotations

import pytest

from . import harness
from .harness import FAKES

IDS = [f.name for f in FAKES]


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_second_sync_adds_nothing_new(fake, monkeypatch, fake_module, tmp_path):
    from lodestone.core.store import get_store

    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 3)
    harness.sync(conn, kwargs)
    after_first = get_store().count()

    second = harness.sync(conn, kwargs)

    assert get_store().count() == after_first, (
        f"{fake.name} duplicated its records on a re-sync: "
        f"{after_first} → {get_store().count()}")
    assert second.added == 0, (
        f"{fake.name} reported {second.added} new memories on an unchanged source")


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_a_repeat_sync_is_not_an_error(fake, monkeypatch, fake_module, tmp_path):
    """Nothing-new is the normal outcome, so it must not show as a failure."""
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 2)
    harness.sync(conn, kwargs)
    second = harness.sync(conn, kwargs)

    assert not second.errors, f"{fake.name} treated an unchanged source as an error"


@pytest.mark.parametrize("fake", FAKES, ids=IDS)
def test_new_records_still_land_after_a_full_sync(fake, monkeypatch, fake_module,
                                                  tmp_path):
    """Dedup must not become "never ingest again".

    A content-hash guard that is too eager is indistinguishable from a broken
    connector: the first sync works, and the source then appears frozen forever.
    """
    from lodestone.core.store import get_store

    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 2)
    harness.sync(conn, kwargs)
    before = get_store().count()

    # Rebuild the same connector against a larger source — records 0 and 1 are
    # byte-identical, records 2 and 3 are new.
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 4)
    if conn.name == "notes":
        kwargs = {"text": "A second, different note about the release plan."}
    result = harness.sync(conn, kwargs)

    assert get_store().count() > before, (
        f"{fake.name} ingested nothing new after its first sync — dedup is "
        "swallowing genuinely new records")
    assert result.added > 0
