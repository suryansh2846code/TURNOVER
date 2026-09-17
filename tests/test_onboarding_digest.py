"""The "Here's your brain" cards say only what the brain actually knows.

The four onboarding cards used to be written in advance. "What you're building
and working on." shipped in the markup, shipped again as the Python fallback,
and shipped a third time as a JavaScript reimplementation of that fallback —
three copies of a sentence nobody had earned, on a screen a person reads as the
app's first finding about them. Underneath, "items" came from a hardcoded
source→area allowlist (every Notion page was work, every connector missing from
the map was work too), and "key themes" were the top entities sliced into four
by list position, so a GitHub repository could be filed under Communication.

Both halves are tested here in one file, deliberately: the contract spans two
layers, and each side passing its own tests is exactly how they came to disagree.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from lodestone.api.routes import brain as brain_routes
from lodestone.brain import Brain
from lodestone.brain.graph import DIGEST_AREAS
from lodestone.core.store import MemoryStore

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"
PAGE = WEB / "onboarding.html"

#: The prose that used to sit on the cards. It must not come back anywhere —
#: not in the markup, not as a Python fallback, not as a JS one.
RETIRED_COPY = (
    "What you're building and working on.",
    "What you're exploring and learning.",
    "Who you talk to and collaborate with.",
    "Your life outside work.",
)


@pytest.fixture
def brain() -> Brain:
    return Brain(store=MemoryStore(db_path=tempfile.mktemp(suffix=".db")))


def _fact(b: Brain, text: str, *, source: str, name: str, etype: str) -> None:
    """One memory from `source`, one entity of `etype`, and the relation that
    ties them together — which is the only thing `areas()` counts."""
    mem = b.store.add(text, source=source, kind="fact", title=name)
    assert mem is not None
    eid = b.graph.upsert_entity(name, type=etype)
    b.graph.add_relation(eid, "mentioned_in", None, text, source_mem=mem.id)


# ── the measured half ───────────────────────────────────────────────────────
def test_an_empty_brain_claims_nothing(brain, monkeypatch):
    monkeypatch.setattr(brain_routes, "get_brain", lambda: brain)
    for p in brain_routes._base_personas():
        assert p["summary"] is None, f"{p['key']} invented a summary from nothing"
        assert p["grounded"] is False
        assert p["items"] == 0 and p["mentions"] == 0
        assert p["themes"] == [] and p["sources"] == []


def test_an_untyped_graph_is_not_reported_as_an_empty_one(brain, monkeypatch):
    """The offline extractor labels everything `thing`. A brain full of those is
    unsorted, not empty, and the page shows a different sentence for each."""
    monkeypatch.setattr(brain_routes, "get_brain", lambda: brain)
    mem = brain.store.add("Atlas ships in March.", source="gmail", kind="fact", title="a")
    assert mem is not None
    eid = brain.graph.upsert_entity("Atlas")          # no type -> "thing"
    brain.graph.add_relation(eid, "mentioned_in", None, "ships", source_mem=mem.id)

    personas = brain_routes._base_personas()
    assert all(not p["grounded"] for p in personas)
    assert brain_routes._graph_is_typed(personas) is False

    _fact(brain, "Priya reviewed it.", source="notion", name="Priya", etype="person")
    assert brain_routes._graph_is_typed(brain_routes._base_personas()) is True


def test_mentions_exist_before_any_fact_does(brain):
    """`items` needs relations, which only enrichment produces. `mentions` is
    maintained on every upsert, so an area is never silently blank."""
    brain.graph.upsert_entity("Priya", type="person")
    comm = brain.graph.areas()["comm"]
    assert comm["items"] == 0
    assert comm["mentions"] == 1
    assert comm["themes"] == ["Priya"]


def test_no_persona_carries_written_in_advance_prose(brain, monkeypatch):
    """The regression itself: a summary nobody earned, on all four cards."""
    monkeypatch.setattr(brain_routes, "get_brain", lambda: brain)
    _fact(brain, "Shipped the parser.", source="github", name="Parser", etype="project")
    blob = json.dumps(brain_routes._base_personas())
    for line in RETIRED_COPY:
        assert line not in blob, f"pre-written copy is back in the API: {line!r}"


def test_an_entity_is_filed_by_what_it_is_not_by_where_it_came_from(brain):
    """A person in a Notion page is Communication; a project in a Gmail thread is
    Work. The source→area allowlist got both of those backwards."""
    _fact(brain, "Priya reviewed the draft.", source="notion", name="Priya", etype="person")
    _fact(brain, "Atlas ships in March.", source="gmail", name="Atlas", etype="project")

    areas = brain.graph.areas()
    assert areas["comm"]["themes"] == ["Priya"]
    assert areas["comm"]["sources"] == ["notion"]
    assert areas["work"]["themes"] == ["Atlas"]
    assert areas["work"]["sources"] == ["gmail"]


def test_themes_are_never_borrowed_from_another_area(brain):
    """Top entities used to be sliced into four buckets by list position."""
    _fact(brain, "Rust has ownership.", source="files", name="Rust", etype="concept")
    areas = brain.graph.areas()
    assert areas["learning"]["themes"] == ["Rust"]
    for other in ("work", "comm", "personal"):
        assert areas[other]["themes"] == [], f"{other} borrowed a theme it has no claim to"


def test_items_counts_memories_not_facts(brain):
    """One memory yielding three facts about one area is one item."""
    mem = brain.store.add("Atlas, Beacon and Cairn all ship in March.",
                          source="linear", kind="fact", title="roadmap")
    assert mem is not None
    for name in ("Atlas", "Beacon", "Cairn"):
        eid = brain.graph.upsert_entity(name, type="project")
        brain.graph.add_relation(eid, "mentioned_in", None, "ships in March", source_mem=mem.id)
    assert brain.graph.areas()["work"]["items"] == 1


def test_an_unknown_source_is_counted_not_dropped(brain):
    """The allowlist silently filed anything it had never heard of under work.
    Attribution comes from the entity now, so a brand-new connector just works."""
    _fact(brain, "A note from somewhere new.", source="a_connector_added_tomorrow",
          name="Helsinki", etype="place")
    personal = brain.graph.areas()["personal"]
    assert personal["items"] == 1
    assert personal["sources"] == ["a_connector_added_tomorrow"]


def test_thing_is_left_unfiled(brain):
    """`thing` is the extractor saying "I could not tell". Spreading those over
    four areas is how a digest starts inventing."""
    _fact(brain, "Something happened.", source="notes", name="Widget", etype="thing")
    assert all(a["items"] == 0 for a in brain.graph.areas().values())
    assert "thing" not in {t for types in DIGEST_AREAS.values() for t in types}


# ── the written half ────────────────────────────────────────────────────────
def test_a_model_may_not_write_about_an_area_with_nothing_in_it(brain, monkeypatch):
    """Asked to describe four areas, a model describes four areas."""
    monkeypatch.setattr(brain_routes, "get_brain", lambda: brain)
    _fact(brain, "Shipped the parser.", source="github", name="Parser", etype="project")
    personas = brain_routes._base_personas()
    assert [p["grounded"] for p in personas] == [True, False, False, False]


# ── the page that renders it ────────────────────────────────────────────────
def _render(digest: dict, connectors: list[dict]) -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/onboarding_digest.mjs"), str(PAGE)],
        input=json.dumps({"digest": digest, "connectors": connectors}),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    assert out["error"] is None, out["error"]
    return out


CONNECTORS = [{"name": "notion", "label": "Notion"}, {"name": "gmail", "label": "Gmail"}]


def _payload(**over) -> dict:
    base = {
        "generated": False, "total": 300, "reason": "no_model", "typed": True,
        "personas": [
            {"key": "work", "title": "Work", "items": 128, "mentions": 400,
             "themes": ["Atlas"], "sources": ["notion"], "summary": None,
             "grounded": True},
            {"key": "learning", "title": "Learning", "items": 12, "mentions": 30,
             "themes": ["Rust"], "sources": ["gmail"],
             "summary": "You have been reading about Rust.", "grounded": True},
            {"key": "comm", "title": "Communication", "items": 1, "mentions": 1,
             "themes": ["Priya"], "sources": ["gmail"], "summary": None,
             "grounded": True},
            {"key": "personal", "title": "Personal", "items": 0, "mentions": 0,
             "themes": [], "sources": [], "summary": None, "grounded": False},
        ],
    }
    base.update(over)
    return base


@pytest.fixture(scope="module")
def rendered() -> dict:
    return _render(_payload(), CONNECTORS)


def _card(rendered: dict, area: str) -> dict:
    return next(c for c in rendered["cards"] if c["area"] == area)


def test_every_card_rendered(rendered):
    assert rendered["ready"] is True
    assert len(rendered["cards"]) == 4


def test_the_page_carries_no_pre_written_copy():
    page = PAGE.read_text()
    for line in RETIRED_COPY:
        assert line not in page, f"pre-written copy is back in the page: {line!r}"


def test_the_page_does_not_compute_personas_of_its_own():
    """A second implementation of the rule is how the card and the brain screen
    end up disagreeing about the same user."""
    assert "computeFallback" not in PAGE.read_text()


def test_a_card_with_data_shows_the_count_and_the_real_themes(rendered):
    work = _card(rendered, "work")
    assert work["items"] == "128 items"
    assert work["themes"] == "Key themes: Atlas"
    assert work["empty"] is False


def test_one_item_is_not_1_items(rendered):
    assert _card(rendered, "comm")["items"] == "1 item"


def test_an_empty_area_says_so_rather_than_filling_the_space(rendered):
    personal = _card(rendered, "personal")
    assert personal["empty"] is True
    assert personal["body"] == "Nothing here yet."
    assert personal["items"] == "" and personal["themes"] == ""


def test_a_written_summary_is_shown_as_written(rendered):
    assert _card(rendered, "learning")["body"] == "You have been reading about Rust."


def test_without_a_model_the_card_says_what_it_read_and_what_to_do(rendered):
    """Never a sentence about the user — only where the material came from, and
    the one thing they can act on."""
    body = _card(rendered, "work")["body"]
    assert "Read from Notion." in body
    assert "Connect an AI model" in body


def test_a_source_is_named_never_keyed(rendered):
    """"notion" is an internal id. The user connected Notion."""
    for card in rendered["cards"]:
        assert "notion" not in card["body"]
        assert "gmail" not in card["body"]


def test_a_source_we_cannot_name_is_left_out_not_surfaced():
    out = _render(_payload(), [])          # no connector list loaded yet
    body = _card(out, "work")["body"]
    assert "notion" not in body and "Read from" not in body
    assert "Connect an AI model" in body


def test_a_model_that_failed_does_not_read_as_a_missing_model():
    out = _render(_payload(reason="model_failed"), CONNECTORS)
    body = _card(out, "work")["body"]
    assert "could not be written just now" in body
    assert "Connect an AI model" not in body


def _all_blank(**over) -> dict:
    return _payload(personas=[
        {"key": k, "title": t, "items": 0, "mentions": 0, "themes": [],
         "sources": [], "summary": None, "grounded": False}
        for k, t in (("work", "Work"), ("learning", "Learning"),
                     ("comm", "Communication"), ("personal", "Personal"))], **over)


def test_an_empty_brain_gets_an_honest_heading():
    out = _render(_all_blank(total=0, reason="no_data", typed=False), CONNECTORS)
    assert "Nothing has landed in your brain yet" in out["head"]
    assert all(c["empty"] for c in out["cards"])
    assert all(c["body"] == "Nothing here yet." for c in out["cards"])


def test_a_full_but_unsorted_brain_is_never_called_empty():
    """The regression this guards: telling somebody with 4,200 memories that
    their work life is empty, because nothing had been typed yet."""
    out = _render(_all_blank(total=4200, reason="no_model", typed=False), CONNECTORS)
    assert "4,200 memories" in out["head"]
    assert "still sorting" in out["head"]
    for card in out["cards"]:
        assert card["body"] == "Still sorting your memories into this one."
        assert "Nothing here yet" not in card["body"]


def test_a_sorted_area_with_nothing_in_it_does_say_so():
    out = _render(_all_blank(total=4200, reason="no_model", typed=True), CONNECTORS)
    assert all(c["body"] == "Nothing here yet." for c in out["cards"])


def test_a_model_summary_stands_on_an_unsorted_brain():
    """Before enrichment nothing is typed, but the model read the real recall
    context — dropping its work there would blank a screen that is genuinely full."""
    payload = _all_blank(total=4200, reason=None, typed=False, generated=True)
    payload["personas"][0].update(summary="You are shipping Atlas at Acme.",
                                  themes=["Atlas"], grounded=True)
    out = _render(payload, CONNECTORS)
    work = _card(out, "work")
    assert work["body"] == "You are shipping Atlas at Acme."
    assert work["themes"] == "Key themes: Atlas"
    assert work["empty"] is False


def test_mentions_are_labelled_as_mentions_not_as_items():
    """Two different true numbers. Calling the second one "items" would be the
    same kind of lie the written-in-advance copy was."""
    payload = _payload()
    payload["personas"][0].update(items=0, mentions=90)
    assert _card(_render(payload, CONNECTORS), "work")["items"] == "90 mentions"


def test_a_card_is_keyed_by_its_declared_area_not_its_position():
    """The four sit by corner. A reordered grid silently relabelling every card
    is exactly the kind of wrong that looks right."""
    shuffled = _payload()
    shuffled["personas"].reverse()
    out = _render(shuffled, CONNECTORS)
    assert _card(out, "personal")["empty"] is True
    assert _card(out, "work")["items"] == "128 items"


# ── when the cards are allowed to appear ────────────────────────────────────
# The digest screen used to arrive on a TIMER: four and a half seconds, or a
# forty-five second cap, whichever came first. It therefore arrived before the
# first enrichment pass had typed a single entity — so the finale of onboarding
# was four cards reading "still sorting", which is the truth and a terrible
# thing to end on. It now waits for the pass, and for the cards to have content.
#
# That is a question about WHEN, which no source-level check can answer, so the
# real block is executed against a scripted backend and a scripted clock.

GROUNDED_DIGEST = {"personas": [
    {"key": "work", "title": "Work", "items": 10, "mentions": 20,
     "themes": ["Atlas"], "sources": ["gmail"],
     "summary": "You ship Atlas.", "grounded": True}]}

BLANK_DIGEST = {"personas": [
    {"key": "work", "title": "Work", "items": 0, "mentions": 0, "themes": [],
     "sources": [], "summary": None, "grounded": False}]}


def _build(**plan) -> dict:
    plan.setdefault("ticks", 400)
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/onboarding_build.mjs"), str(PAGE)],
        input=json.dumps(plan), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    assert out["error"] is None, out["error"]
    return out


def _synced(total=1200):
    return [{"total": 0, "graph": {"entities": 0}}] * 3 + \
           [{"total": total, "graph": {"entities": 300}}]


def test_the_cards_wait_for_the_first_enrichment_pass():
    """Mid-enrichment the build screen is still up, and it is reporting the
    pass's own numbers rather than a timer dressed up as one."""
    out = _build(
        stats=_synced(),
        sync=[{"syncing": True}] * 60 + [{"syncing": False}],
        enrich=[{"running": True, "processed": i * 30, "remaining": 1200 - i * 30}
                for i in range(40)] + [{"running": False, "processed": 1200, "remaining": 0}],
        digest=GROUNDED_DIGEST, ticks=80)

    assert out["startedEnrichment"] is True
    midway = next(t for t in out["timeline"] if t["tick"] == 20)
    assert midway["handedOver"] is False, "the digest appeared while enrichment was still running"
    assert "600 of 1,200" in midway["detail"], "progress was not the enrichment's own count"
    assert out["handedOver"] is True


def test_nothing_to_show_means_the_build_screen_stays():
    """The whole point: no digest until a card has something true on it."""
    out = _build(
        stats=_synced(900),
        sync=[{"syncing": True}],
        enrich=[{"running": True, "processed": 10, "remaining": 0}] * 6
               + [{"running": False, "processed": 10, "remaining": 0}],
        digest=BLANK_DIGEST, ticks=340)

    assert out["handedOver"] is False
    assert out["stillBuilding"] is True
    assert out["digestFetches"] > 1, "it never asked again while the sync kept running"


def test_a_long_wait_is_never_a_trap():
    """Anything the user starts, they can leave."""
    out = _build(
        stats=_synced(900), sync=[{"syncing": True}],
        enrich=[{"running": True, "processed": 10, "remaining": 0}] * 6
               + [{"running": False, "processed": 10, "remaining": 0}],
        digest=BLANK_DIGEST, ticks=340)
    assert any(t["skipShown"] for t in out["timeline"]), "no way out was ever offered"
    assert not out["timeline"][0]["skipShown"], "the way out was offered immediately"


def test_continue_anyway_lets_the_user_through():
    out = _build(
        stats=_synced(900), sync=[{"syncing": True}],
        enrich=[{"running": True, "processed": 10, "remaining": 0}] * 6
               + [{"running": False, "processed": 10, "remaining": 0}],
        digest=BLANK_DIGEST, ticks=340, clickSkipAtTick=230)
    assert out["handedOver"] is True


def test_enrichment_that_cannot_run_is_skipped_not_waited_on():
    """No model connected: the pass never starts. That is a reason to move on
    with what is known, not to hold somebody on a progress bar forever."""
    out = _build(
        stats=_synced(900), sync=[{"syncing": False}],
        enrich=[{"running": False, "processed": 0, "remaining": 900}],
        digest=GROUNDED_DIGEST, ticks=80)
    assert out["handedOver"] is True
