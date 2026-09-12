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


def test_auth_start_publishes_the_timeout():
    with patch("lodestone.models.cursor.find_cursor_cli", return_value="/x/agent"), \
         patch("lodestone.models.cursor.cursor_cli_auth_status",
               return_value={"installed": True, "authenticated": False}), \
         patch("lodestone.models.cursor.start_cursor_cli_login", return_value=(True, "opened")):
        body = TestClient(app).post("/api/providers/cursor/auth/start").json()
    assert body["started"] is True
    assert body["timeout_seconds"] == hud.SIGNIN_TIMEOUT_SECONDS


def test_the_api_does_not_try_to_open_the_window():
    """Under `lodestone app --dev` the backend is a separate uvicorn process
    with no handle on the webview, so a backend-raised window silently did
    nothing. The page raises it instead."""
    src = (ROOT / "lodestone/api/app.py").read_text()
    assert "hud.open_signin(" not in src


def test_the_frontend_raises_the_card_and_stands_down():
    src = (ROOT / "lodestone/web/app.js").read_text()
    assert "open_signin_hud" in src, "the page never asks the webview for a window"
    assert "raiseFloatingSigninCard" in src
    # and it must degrade when there is no webview bridge (browser mode)
    fn = src[src.index("async function raiseFloatingSigninCard"):]
    fn = fn[:fn.index("\nfunction ")]
    assert "return false" in fn


def test_window_is_prepared_up_front_and_floats():
    """Built once, hidden, on the main thread — creating and destroying windows
    from the js_api worker thread is cross-thread Cocoa work we avoid."""
    created = {}

    def fake_create_window(title, url, **kw):
        created.update(kw)
        return MagicMock()

    screen = MagicMock(x=0, y=0, width=1470, height=956)
    with patch.dict("sys.modules", {"webview": MagicMock(screens=[screen])}):
        hud.prepare(fake_create_window)

    assert created["hidden"] is True, "must not flash on screen at startup"
    assert created["on_top"] is True, "floating above other apps is the point"
    assert created["frameless"] is True
    assert created["easy_drag"] is True, "a frameless window must be movable"
    assert created["x"] > 900 and created["y"] < 60, "not in the top-right corner"


def test_showing_reuses_the_window_rather_than_creating_one():
    window = MagicMock()
    hud.configure("http://127.0.0.1:9999", MagicMock())
    hud._hud_window = window
    screen = MagicMock(x=0, y=0, width=1470, height=956)
    with patch.dict("sys.modules", {"webview": MagicMock(screens=[screen])}):
        assert hud.open_signin("xai", "Grok", "https://auth.x.ai/c") is True

    url = window.load_url.call_args[0][0]
    assert "provider=xai" in url and "brand=Grok" in url
    assert f"limit={hud.SIGNIN_TIMEOUT_SECONDS}" in url
    window.show.assert_called_once()
    window.destroy.assert_not_called()


def test_closing_hides_and_stops_the_page_polling():
    window = MagicMock()
    hud._hud_window = window
    hud.close()
    window.hide.assert_called_once()
    window.load_url.assert_called_with("about:blank")
    window.destroy.assert_not_called()


def test_close_is_safe_when_nothing_is_open():
    hud.close()          # must not raise


def test_a_window_failure_does_not_break_sign_in():
    window = MagicMock()
    window.show.side_effect = RuntimeError("no display")
    hud.configure("http://127.0.0.1:9999", MagicMock())
    hud._hud_window = window
    with patch.dict("sys.modules", {"webview": MagicMock(screens=[])}):
        assert hud.open_signin("xai", "Grok") is False


def test_cancelling_stops_the_flow_and_hides_the_card():
    """Dismissing the card must actually abandon the sign-in, not just hide it."""
    window = MagicMock()
    hud._hud_window = window
    cancelled = {}
    flow = MagicMock(cancel=lambda: cancelled.setdefault("called", True))
    with patch("lodestone.models.auth_flows.get_flow", return_value=flow):
        assert hud._Bridge().cancel_signin("cursor") is True
    assert cancelled.get("called") is True
    window.hide.assert_called_once()


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


def test_the_card_offers_a_way_to_cancel():
    html = HUD_HTML.read_text()
    assert 'id="cancel"' in html and "Cancel sign-in" in html
    assert "/auth/cancel" in html, "the button must abandon the flow, not just close"


def test_the_models_card_cancel_abandons_the_flow():
    src = (ROOT / "lodestone/web/app.js").read_text()
    assert "/auth/cancel" in src, "in-app Cancel only hid the spinner"


def test_the_poll_does_not_hammer_the_expensive_endpoint():
    """/refresh re-runs discovery and takes seconds per provider; calling it
    every tick queued requests faster than the server could finish them and
    froze the whole app."""
    src = (ROOT / "lodestone/web/app.js").read_text()
    hudfn = src[src.index("function showWaitingHud"):]
    hudfn = hudfn[:hudfn.index("\nfunction ")]
    loop = hudfn[hudfn.index("pollTimer = setInterval"):]
    # Strip comments so the rule is checked against code, not prose.
    code = "\n".join(l for l in loop.splitlines() if not l.strip().startswith("//"))
    before_success = code[:code.index('st.status === "success"')]
    assert "/refresh" not in before_success, "refresh is called before knowing it succeeded"


def test_loader_animation_is_present():
    css = HUD_HTML.read_text()
    assert "@keyframes orbit" in css and ".loader i" in css
