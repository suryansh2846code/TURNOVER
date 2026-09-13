"""`"key" in row` does not mean what it looks like on a sqlite3.Row.

`sqlite3.Row` supports `row["col"]` and `row.keys()`, but its `__contains__`
tests the row's **values**, not its keys — so `if "importance" in row` is False
for a row that has an `importance` column, and True for a row whose *text*
happens to be "importance".

The graph store guarded every optional column that way. The guards were
therefore always False, the defaults were used instead of the stored numbers,
and entity importance and confidence never moved off 0.5/0.8 no matter what was
written. These tests pin both the language behaviour and the fix.
"""
import sqlite3

import pytest

from lodestone.brain.graph import _num


def test_row_membership_tests_values_not_keys():
    """The language behaviour the bug rested on. If this ever changes, the
    workarounds below can be simplified — until then they are load-bearing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 'thing' AS importance, 0.9 AS confidence").fetchone()

    assert "importance" not in row, "sqlite3.Row membership now tests keys"
    assert "importance" in row.keys()
    assert "thing" in row, "membership matches a VALUE"


def test_num_reads_the_stored_value():
    assert _num(0.93, 0.5) == pytest.approx(0.93)
    assert _num(0, 0.5) == 0.0, "a stored zero is a value, not a missing column"
    assert _num(None, 0.5) == 0.5, "NULL falls back"


@pytest.fixture
def graph(tmp_path):
    from lodestone.brain import Brain
    from lodestone.core.store import MemoryStore

    return Brain(store=MemoryStore(db_path=str(tmp_path / "brain.db"))).graph


def test_entity_confidence_is_actually_stored_and_returned(graph):
    """The user-visible symptom: a high-confidence entity read back as 0.8."""
    eid = graph.upsert_entity("Ada Lovelace", type="person", confidence=0.97)
    entity = graph.get_entity(eid)
    assert entity is not None
    assert entity["confidence"] == pytest.approx(0.97), (
        'confidence was discarded — the `"confidence" in row` guard is back')


def test_importance_climbs_as_an_entity_is_seen_again(graph):
    """`new_imp = min(1.0, stored + 0.05)`. With the guard in place `stored` was
    always the 0.5 default, so importance never accumulated across mentions."""
    eid = graph.upsert_entity("Recurring Project", type="project")
    first = graph.get_entity(eid)["importance"]
    for _ in range(4):
        graph.upsert_entity("Recurring Project", type="project")
    later = graph.get_entity(eid)["importance"]
    assert later > first, "importance is not accumulating across mentions"
    assert later == pytest.approx(min(1.0, first + 4 * 0.05), abs=1e-6)


def test_matching_reports_the_stored_numbers(graph):
    """`match_entities` is what recall ranks on; it read the same guarded
    columns, so every candidate looked equally important."""
    graph.upsert_entity("Vector Databases", type="topic", confidence=0.95)
    hits = graph.match_entities("Vector Databases")
    assert hits, "entity did not match its own name"
    assert hits[0]["confidence"] == pytest.approx(0.95)


def test_aliases_still_round_trip(graph):
    """The alias lookups use `.keys()` for the same reason; a regression there
    would silently stop matching entities by their other names."""
    graph.upsert_entity("International Business Machines", type="org",
                        aliases=["IBM"])
    assert graph.match_entities("IBM"), "alias lookup stopped working"
