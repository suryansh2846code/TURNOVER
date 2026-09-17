"""The free heuristic enrichment pass runs.

`_auto_graphable` read `self._PROSE_EXT`, which was defined nowhere. Every
heuristic pass therefore raised `AttributeError` on the first memory carrying a
uri — and `scheduler._sync_all` catches and logs that, so it failed silently
after every sync for as long as it shipped. The visible symptom was a graph that
stayed empty while the memory count climbed, and a terminal filling with
tracebacks nobody read.

This is the pass that has to work for the offline case: no model connected, no
tokens spent. It is also what the onboarding build screen now waits on before it
shows the digest, so a silent failure there is a screen that waits and then
shows four cards with nothing on them.
"""
from __future__ import annotations

import tempfile

import pytest

from chitragupta.brain import Brain
from chitragupta.brain.brain import _prose_suffixes
from chitragupta.connectors.files import PROSE_EXT
from chitragupta.core.store import MemoryStore


@pytest.fixture
def brain() -> Brain:
    return Brain(store=MemoryStore(db_path=tempfile.mktemp(suffix=".db")))


def test_a_prose_file_does_not_crash_the_pass(brain):
    """The regression, exactly: one memory with a uri, one heuristic pass."""
    brain.store.add("Priya is leading the Atlas launch in March.",
                    source="files", kind="doc", title="atlas",
                    uri="/Users/me/notes/atlas.md")
    out = brain.enrich_until_done(fast=True, max_batches=1)
    assert out["processed"] == 1
    assert brain.graph.stats()["entities"] > 0, "nothing was extracted"


def test_every_suffix_the_connector_ingests_is_recognised():
    """Two lists of what counts as prose would drift, and the copy that drifts
    is the one you are not looking at."""
    assert set(_prose_suffixes()) == set(PROSE_EXT)


def test_the_suffixes_are_a_tuple_because_endswith_rejects_a_set():
    """`str.endswith` takes a str or a tuple. Handed the connector's set it
    raises TypeError — so importing PROSE_EXT directly would have swapped one
    crash for another."""
    assert isinstance(_prose_suffixes(), tuple)
    with pytest.raises(TypeError):
        "atlas.md".endswith(PROSE_EXT)


def test_a_prose_file_is_graphable_and_a_spreadsheet_is_not(brain):
    prose = brain.store.add("A note.", source="files", kind="doc",
                            title="a", uri="/x/a.md")
    sheet = brain.store.add("Rows and columns.", source="files", kind="doc",
                            title="b", uri="/x/b.xlsx")
    assert brain._auto_graphable(prose) is True
    # Not prose, and not one of the high-signal sources or kinds either.
    assert brain._auto_graphable(sheet) is False


def test_a_memory_with_no_uri_is_unaffected(brain):
    """The uri branch is one of three, and the other two must still answer."""
    note = brain.store.add("Remember the milk.", source="notes", kind="note",
                           title="milk")
    assert brain._auto_graphable(note) is True
