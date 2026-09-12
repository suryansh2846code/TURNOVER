"""The floating sign-in card.

A browser sign-in takes the user out of Lodestone, so the status has to follow
them: an always-on-top window that sits above the browser, reports success, and
offers a way back. It exists only in the desktop app — `lodestone serve` has no
window to create, so the in-app card must still handle it there.
"""
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lodestone import hud
from lodestone.api.app import app

ROOT = Path(__file__).parent.parent
HUD_HTML = ROOT / "lodestone/web/signin_hud.html"
HARNESS = ROOT / "tests/js/signin_hud.mjs"


@pytest.fixture(autouse=True)
def _reset_hud():
    hud._origin, hud._main_window, hud._hud_window = None, None, None
    yield
    hud._origin, hud._main_window, hud._hud_window = None, None, None


# ── degrades to the in-app card outside the desktop app ──────────────────
def test_no_window_outside_the_desktop_app():
    assert hud.available() is False
    assert hud.open_signin("xai", "Grok", "https://x") is False


def test_auth_start_reports_which_card_took_over():
    """Both would otherwise appear at once in the desktop app."""
    with patch("lodestone.models.cursor.find_cursor_cli", return_value="/x/agent"), \
         patch("lodestone.models.cursor.cursor_cli_auth_status",
               return_value={"installed": True, "authenticated": False}), \
         patch("lodestone.models.cursor.start_cursor_cli_login", return_value=(True, "opened")):
        body = TestClient(app).post("/api/providers/cursor/auth/start").json()
    assert body["started"] is True
    assert body["floating_hud"] is False, "no desktop window, so the in-app card runs"
    assert body["timeout_seconds"] == hud.SIGNIN_TIMEOUT_SECONDS


def test_the_frontend_stands_down_when_the_floating_card_opened():
    src = (ROOT / "lodestone/web/app.js").read_text()
    assert "res.floating_hud" in src, "in-app card would stack on top of the floating one"


# ── the window itself ────────────────────────────────────────────────────
def test_window_floats_above_other_apps():
    """The whole point: the user is in their browser, not in Lodestone."""
    created = {}

    def fake_create_window(title, url, **kw):
        created["title"], created["url"], created["kw"] = title, url, kw
        return MagicMock()

    hud.configure("http://127.0.0.1:9999", MagicMock())
    with patch.dict("sys.modules", {"webview": MagicMock(create_window=fake_create_window)}):
        assert hud.open_signin("xai", "Grok", "https://auth.x.ai/c") is True

    assert created["kw"]["on_top"] is True
    assert created["kw"]["frameless"] is True
    assert created["kw"]["easy_drag"] is True, "a frameless window must be movable"
    assert "provider=xai" in created["url"] and "brand=Grok" in created["url"]
    assert f"limit={hud.SIGNIN_TIMEOUT_SECONDS}" in created["url"]


def test_opening_twice_replaces_rather_than_stacks():
    windows = [MagicMock(), MagicMock()]
    hud.configure("http://127.0.0.1:9999", MagicMock())
    with patch.dict("sys.modules",
                    {"webview": MagicMock(create_window=MagicMock(side_effect=windows))}):
        hud.open_signin("xai", "Grok")
        hud.open_signin("cursor", "Cursor")
    windows[0].destroy.assert_called_once()


def test_close_is_safe_when_nothing_is_open():
    hud.close()          # must not raise


def test_a_window_failure_does_not_break_sign_in():
    hud.configure("http://127.0.0.1:9999", MagicMock())
    with patch.dict("sys.modules",
                    {"webview": MagicMock(create_window=MagicMock(side_effect=RuntimeError("no display")))}):
        assert hud.open_signin("xai", "Grok") is False


def test_timeout_is_generous_enough_for_a_real_sign_in():
    """Switching accounts with a password and 2FA blew past a 150s poll in
    practice, so this must not be tightened without evidence."""
    assert hud.SIGNIN_TIMEOUT_SECONDS >= 180


# ── the page renders and reaches each state ──────────────────────────────
def test_page_is_served():
    r = TestClient(app).get("/signin-hud?provider=xai&brand=Grok")
    assert r.status_code == 200 and "Waiting to connect" in r.text


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("scenario,expect", [
    ("success", {"title": "Grok is connected", "action": "Return to Lodestone", "cls": "is-ok"}),
    ("timeout", {"title": "Couldn't connect Grok", "action": "Try again", "cls": "is-err"}),
])
def test_states_render(scenario, expect):
    proc = subprocess.run(["node", str(HARNESS), str(HUD_HTML), scenario],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[:400]
    got = json.loads(proc.stdout)
    assert got["title"] == expect["title"]
    assert got["action"] == expect["action"]
    assert expect["cls"] in got["cardClass"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_success_names_the_account():
    proc = subprocess.run(["node", str(HARNESS), str(HUD_HTML), "success"],
                          capture_output=True, text=True, timeout=60)
    assert "me@example.com" in json.loads(proc.stdout)["body"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_it_actually_polls_for_status():
    proc = subprocess.run(["node", str(HARNESS), str(HUD_HTML), "success"],
                          capture_output=True, text=True, timeout=60)
    assert json.loads(proc.stdout)["polled"] >= 1


def test_loader_animation_is_present():
    css = HUD_HTML.read_text()
    assert "@keyframes orbit" in css and ".loader i" in css
