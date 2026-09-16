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
from web_sources import app_source

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"
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


@pytest.mark.parametrize("nav,panel", [("model", "model"), ("sources", "connectors"),
                                       ("inbox", "inbox")])
def test_a_settings_item_opens_the_screen_on_its_own_panel(clicked, nav, panel):
    """Model and Connectors share one shell, so opening the screen is only half
    of it — landing on the wrong panel shows the screen with the other page on
    it, which reads as the nav item doing nothing."""
    got = clicked["opened"][nav]
    assert got["modelScreen"] is True and got["drawer"] is False, got
    assert got["panel"] == panel, (
        f"{nav} opened the settings screen on the {got['panel']!r} panel")


@pytest.mark.parametrize("nav", ["tasks", "tools"])
def test_the_remaining_drawers_are_still_drawers(clicked, nav):
    """The delegation must catch the two that became screens and nothing else."""
    got = clicked["opened"][nav]
    assert got["modelScreen"] is False and got["drawer"] is True, (
        f"{nav} was dragged onto the settings screen — the openDrawer "
        "delegation is matching more than it should"
    )


def test_the_screen_can_be_closed(clicked):
    assert clicked["opened"]["closeButtonWorks"] is True


# ── the panel really left the drawer ──────────────────────────────────────
def test_routines_and_reminders_left_the_tasks_drawer():
    """Two homes for the same list means one of them is the stale one."""
    tasks_panel = INDEX.split('data-d="tasks"', 1)[1].split("</div>\n\n", 1)[0]
    assert 'id="routineList"' not in tasks_panel
    assert 'id="reminderList"' not in tasks_panel


def test_no_sources_panel_is_left_inside_the_drawer():
    assert 'data-d="sources"' not in INDEX, (
        "the drawer still has a sources panel — two copies of #connectors would "
        "mean the renderer fills whichever the DOM happens to return first")


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


def _rule(selector: str) -> str:
    assert selector in CSS, f"{selector} is gone from styles.css"
    return CSS.split(selector, 1)[1].split("}", 1)[0]


def test_providers_are_a_single_settings_column():
    """Deliberate change from the first version of this screen.

    It shipped as a responsive grid of cards, which read as a dashboard. The
    page is a settings page, so providers are now one centred column of
    sections — the grid assertion this replaces was testing the old intent.
    """
    assert "column" in _rule(".modelscreen .provider-cards")


def test_each_provider_group_is_one_card_of_rows():
    """The look the screen exists for: one card per provider, hairline rows.

    The provider markup emits a separate .ts-card per credential. If those keep
    their own borders the group renders as a stack of little boxes again, which
    is exactly what it looked like before.
    """
    group = _rule(".modelscreen .ts-group-boxes")
    assert "border" in group and "radius" in group, group
    flattened = _rule(".modelscreen .ts-group-boxes .ts-card")
    assert "border: 0" in flattened, flattened


def test_the_provider_boxes_are_not_spaced_apart():
    """An inline margin between boxes would put gaps inside the single card."""
    assert 'id="pbox_${pid}" style="margin-bottom' not in app_source()


def test_nothing_calls_it_a_drawer_any_more():
    assert "Models drawer" not in app_source(), (
        "user-facing copy still calls the model screen a drawer"
    )
