"""The floating sign-in window.

A browser sign-in takes the user out of Lodestone, so the status has to follow
them. This is a small always-on-top, frameless window that sits above the
browser while they authorise, then tells them it worked and offers a way back.

It only exists in the desktop app. `lodestone serve` has no window to create,
so every call here is a no-op and the in-app card handles it instead — the
product must work in both modes.

**The window is opened from the page, not from the API.** Under
`lodestone app --dev` the backend runs as a separate uvicorn process, which has
no handle on the webview at all — a backend-initiated window silently did
nothing there. The frontend always runs inside the webview, so it calls
`window.pywebview.api.open_signin_hud(...)` and this module does the rest.

**The window is created once, hidden, on the main thread** and then shown and
hidden as needed. Creating and destroying windows from the js_api worker thread
is the kind of cross-thread Cocoa work that is easy to get wrong; show/hide of a
pre-made window is a plain, thread-safe call.
"""
from __future__ import annotations

import logging
import threading
import urllib.parse

logger = logging.getLogger(__name__)

# How long we wait for a browser sign-in before giving up. Deliberately generous:
# switching accounts, typing a password and clearing 2FA regularly takes longer
# than two minutes, and a HUD that gives up while the user is mid-flow reads as
# the app being broken.
SIGNIN_TIMEOUT_SECONDS = 180

_WINDOW_SIZE = (420, 290)
_SCREEN_MARGIN = 18          # gap from the screen edge, like a system notification

# Set by desktop.run_app; absent when running as a plain server.
_origin: str | None = None
_main_window = None
_hud_window = None
# What the last sign-in click actually did. Without this, "the card showed up in
# the wrong place" is unanswerable: the branch that never reached the floating
# card and the branch that reached it and failed look identical from outside.
_trail: list[dict] = []
_lock = threading.Lock()


def configure(origin: str, main_window) -> None:
    """Called by the desktop app once its window exists."""
    global _origin, _main_window
    _origin, _main_window = origin, main_window


def available() -> bool:
    return _origin is not None and _main_window is not None


def _corner_position(width: int, height: int) -> tuple[int | None, int | None]:
    """Top-right of the primary screen, where system notifications appear."""
    try:
        import webview

        screen = webview.screens[0]
        return (screen.x + screen.width - width - _SCREEN_MARGIN,
                screen.y + _SCREEN_MARGIN)
    except Exception:
        return None, None


class _Bridge:
    """Exposed to the HUD page as `window.pywebview.api`."""

    def close_hud(self) -> None:
        close()

    def cancel_signin(self, provider: str) -> bool:
        """Abandon an in-progress sign-in and put the card away."""
        close()
        try:
            from .models.auth_flows import get_flow

            cancel = getattr(get_flow(provider), "cancel", None)
            if cancel is not None:
                cancel()
            return True
        except Exception:
            logger.debug("could not cancel %s sign-in", provider, exc_info=True)
            return False

    def focus_main(self) -> None:
        close()
        try:
            if _main_window is not None:
                _main_window.show()
                _main_window.on_top = True      # bring it forward…
                _main_window.on_top = False     # …without pinning it there
        except Exception:
            logger.debug("could not focus the main window", exc_info=True)


def prepare(create_window) -> None:
    """Build the (hidden) window up front, on the main thread."""
    global _hud_window
    width, height = _WINDOW_SIZE
    x, y = _corner_position(width, height)
    try:
        _hud_window = create_window(
            "Connect", "about:blank",
            width=width, height=height, x=x, y=y,
            hidden=True, frameless=True, easy_drag=True, on_top=True,
            resizable=False, shadow=True, focus=True, js_api=_Bridge(),
        )
    except Exception:
        logger.warning("could not prepare the sign-in window", exc_info=True)
        _hud_window = None


def note(event: str, **fields) -> None:
    """Record a step of the sign-in path. Bounded; support signal, not a log."""
    _trail.append({"event": event, **fields})
    del _trail[:-12]


def open_signin(provider: str, brand: str, auth_url: str = "") -> bool:
    """Show the floating card for an in-progress sign-in. False if unavailable."""
    if not available() or _hud_window is None:
        note("open_signin", provider=provider, ok=False,
             reason="no native window in this process")
        return False

    query = urllib.parse.urlencode({
        "provider": provider, "brand": brand,
        "auth_url": auth_url, "limit": SIGNIN_TIMEOUT_SECONDS,
    })
    with _lock:
        try:
            _hud_window.load_url(f"{_origin}/signin-hud?{query}")
            width, height = _WINDOW_SIZE
            x, y = _corner_position(width, height)
            if x is not None:
                _hud_window.move(x, y)
            _hud_window.show()
            note("open_signin", provider=provider, ok=True)
            return True
        except Exception:
            logger.warning("could not show the sign-in window", exc_info=True)
            note("open_signin", provider=provider, ok=False, reason="show failed")
            return False


def diagnostics() -> dict:
    """Why the floating card is or isn't available — for support, not for flow
    control. Silence here is what made this hard to diagnose."""
    return {
        "origin_set": _origin is not None,
        "main_window": _main_window is not None,
        "hud_window_prepared": _hud_window is not None,
        "available": available(),
        "trail": list(_trail),
    }


def close() -> None:
    """Hide the card. The window is reused, never destroyed — tearing one down
    from a worker thread is exactly the cross-thread work we are avoiding."""
    if _hud_window is None:
        return
    try:
        _hud_window.hide()
        _hud_window.load_url("about:blank")     # stop the page polling
    except Exception:
        logger.debug("sign-in window already hidden", exc_info=True)
