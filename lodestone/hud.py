"""The floating sign-in window.

A browser sign-in takes the user out of Lodestone, so the status has to follow
them. This is a small always-on-top, frameless window that sits above the
browser while they authorise, then tells them it worked and offers a way back.

It only exists in the desktop app. `lodestone serve` has no window to create,
so every call here is a no-op and the in-app card handles it instead — the
product must work in both modes.
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

_WINDOW_SIZE = (440, 300)

# Set by desktop.run_app; absent when running as a plain server.
_origin: str | None = None
_main_window = None
_hud_window = None
_lock = threading.Lock()


def configure(origin: str, main_window) -> None:
    """Called by the desktop app once its window exists."""
    global _origin, _main_window
    _origin, _main_window = origin, main_window


def available() -> bool:
    return _origin is not None and _main_window is not None


class _Bridge:
    """Exposed to the HUD page as `window.pywebview.api`."""

    def close_hud(self) -> None:
        close()

    def focus_main(self) -> None:
        close()
        try:
            if _main_window is not None:
                _main_window.show()
                _main_window.on_top = True      # bring it forward…
                _main_window.on_top = False     # …without pinning it there
        except Exception:
            logger.debug("could not focus the main window", exc_info=True)


def open_signin(provider: str, brand: str, auth_url: str = "") -> bool:
    """Show the floating card for an in-progress sign-in. False if unavailable."""
    if not available():
        return False

    import webview

    query = urllib.parse.urlencode({
        "provider": provider, "brand": brand,
        "auth_url": auth_url, "limit": SIGNIN_TIMEOUT_SECONDS,
    })
    url = f"{_origin}/signin-hud?{query}"

    with _lock:
        close()
        try:
            global _hud_window
            width, height = _WINDOW_SIZE
            _hud_window = webview.create_window(
                f"Connect {brand}", url,
                width=width, height=height,
                frameless=True, easy_drag=True, on_top=True,
                resizable=False, shadow=True, transparent=True,
                focus=True, js_api=_Bridge(),
            )
            return True
        except Exception:
            logger.warning("could not open the sign-in window", exc_info=True)
            _hud_window = None
            return False


def close() -> None:
    global _hud_window
    window, _hud_window = _hud_window, None
    if window is None:
        return
    try:
        window.destroy()
    except Exception:
        logger.debug("sign-in window already closed", exc_info=True)
