"""One bad item must never abort a sync.

This is decision H2, and it is written correctly in some connectors and not
others — `gmail.py` wraps each message, `apple_mail.py` wraps nothing. The
difference has never been visible because no test ran either loop.

It matters more than it looks. A sync is how the brain gets built; a single
malformed record aborting the pass means the user loses everything after it and
sees "sync failed" with no way to find the offending item. Worse, it is
*silently* partial — the memories before the bad one are already committed, so
the brain looks populated and is quietly missing half the source.

The probe breaks one item at the ingest seam, which is the same for every
connector regardless of whether it writes through `Brain.ingest` or
`MemoryStore.add`.
"""
from __future__ import annotations

import pytest

from . import harness
from .harness import FAKES

# Connectors that fold many source records into one memory (an iMessage thread)
# or take a single record per call (notes) cannot lose "the rest of the batch",
# so the probe has nothing to prove there.
BATCHED = {f for f in FAKES if f.name not in ("imessage", "notes")}
IDS = [f.name for f in BATCHED]


@pytest.mark.parametrize("fake", sorted(BATCHED, key=lambda f: f.name), ids=sorted(IDS))
def test_one_bad_item_does_not_abort_the_sync(fake, monkeypatch, fake_module,
                                              tmp_path, poison):
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 3)
    breaker = poison(nth=2)

    result = harness.sync(conn, kwargs)

    assert breaker.raised, (
        f"{fake.name} never reached the poisoned item — the fixture is not "
        "exercising the ingest loop, so this test proves nothing")
    assert result.added >= 2, (
        f"{fake.name} lost the items after the bad one: added={result.added}. "
        "One malformed record must be skipped, not abort the pass (H2)")


@pytest.mark.parametrize("fake", sorted(BATCHED, key=lambda f: f.name), ids=sorted(IDS))
def test_a_bad_item_is_counted_not_hidden(fake, monkeypatch, fake_module,
                                          tmp_path, poison):
    """Surviving is not enough — the user must be able to see something was
    dropped, or a half-ingested source reads as a complete one."""
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 3)
    poison(nth=2)

    result = harness.sync(conn, kwargs)

    assert result.skipped >= 1 or result.errors, (
        f"{fake.name} dropped an item and reported neither a skip nor an error")


@pytest.mark.parametrize("fake", sorted(BATCHED, key=lambda f: f.name), ids=sorted(IDS))
def test_the_sync_never_raises(fake, monkeypatch, fake_module, tmp_path, poison):
    """`sync()` returns a SyncResult even when everything inside it fails.

    The scheduler does catch exceptions (`scheduler.py:78`), but catching one
    costs the detail: every failure collapses to the same opaque string instead
    of the connector's own explanation.
    """
    conn, kwargs = harness.build(fake, monkeypatch, fake_module, tmp_path, 2)
    poison(nth=1)

    result = harness.sync(conn, kwargs)     # must not raise

    assert result.connector == conn.name
