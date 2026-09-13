"""AI model is a screen of its own, and only it moved.

It used to be one of four panels in the 380px slide-over — the wrong shape for
a grid of provider cards that each carry an account, a plan, usage limits and
a model list.

Four separate call sites open it (the left nav, plus three "connect in Models"
affordances in the composer), so the move is done by delegating inside
`openDrawer()` instead of editing each one. That is the part worth testing: a
delegation that matched too greedily would quietly send Tasks, Connectors and
Tools to the model screen as well, and every one of those still reads as
correct in the source. So the nav items are clicked for real.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"
INDEX = (WEB / "index.html").read_text()
CSS = (WEB / "styles.css").read_text()


@pytest.fixture(scope="module")
def clicked() -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/open_model_screen.mjs"), str(WEB / "app.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_the_harness_reached_the_handlers(clicked):
    assert clicked["error"] is None, clicked["error"]


def test_model_opens_the_full_screen_and_not_the_drawer(clicked):
    assert clicked["opened"]["model"] == {"modelScreen": True, "drawer": False}


@pytest.mark.parametrize("nav", ["tasks", "tools", "sources"])
def test_every_other_nav_item_still_opens_the_drawer(clicked, nav):
    """The delegation must catch "model" and nothing else."""
    assert clicked["opened"][nav] == {"modelScreen": False, "drawer": True}, (
        f"{nav} was dragged along with the model screen — the openDrawer "
        "delegation is matching more than it should"
    )


def test_the_screen_can_be_closed(clicked):
    assert clicked["opened"]["closeButtonWorks"] is True


# ── the panel really left the drawer ──────────────────────────────────────
def test_no_model_panel_is_left_inside_the_drawer():
    assert 'data-d="model"' not in INDEX, (
        "the drawer still has a model panel — two copies of these ids would "
        "mean loadProviders() fills whichever the DOM happens to return first"
    )


def test_the_screen_exists_and_starts_hidden():
    assert '<div id="modelScreen" class="modelscreen" hidden>' in INDEX


@pytest.mark.parametrize("element_id", [
    "providerCards", "enrichProvider", "enrichModelName", "enrichCap",
    "enrichCapSave", "enrichCapNote", "usageBox", "usageReset",
    # the hidden fallbacks older code still reads
    "agentModelMatrix", "provider", "defaultProviderConnectBox", "modelName",
    "modelHint", "privacyBadge",
])
def test_every_id_the_model_code_reads_survived_the_move(element_id):
    assert f'id="{element_id}"' in INDEX, (
        f"#{element_id} was dropped when the panel moved — the code that reads "
        "it will silently do nothing"
    )


def test_ids_are_not_duplicated_across_the_page():
    """A second copy of any of these would make the move a no-op for one of them."""
    import re
    ids = re.findall(r'id="([^"]+)"', INDEX)
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate element ids: {sorted(dupes)}"


def test_the_cards_are_a_grid_on_the_screen():
    """The whole point of the move: cards stop being a single narrow column."""
    assert ".modelscreen .provider-cards" in CSS
    block = CSS.split(".modelscreen .provider-cards", 1)[1].split("}", 1)[0]
    assert "grid" in block and "minmax" in block, block


def test_nothing_calls_it_a_drawer_any_more():
    app_js = (WEB / "app.js").read_text()
    assert "Models drawer" not in app_js, (
        "user-facing copy still calls the model screen a drawer"
    )
