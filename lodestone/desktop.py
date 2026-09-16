"""Desktop app — run Lodestone as a native window instead of a browser tab.

Starts the FastAPI server in a background thread and shows the UI in a native
webview window. `lodestone app` launches it; the macOS .app bundle calls the
same entry point.
"""
from __future__ import annotations

import socket
import threading
import time

from .log import suppressed


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _bind(host: str, port: int) -> socket.socket:
    """Bind a listening socket the way uvicorn would.

    SO_REUSEADDR is not a detail here. A server that has just exited leaves
    connections in TIME_WAIT, and a plain bind on that port fails while uvicorn's
    would succeed — so a probe without it calls the port taken one launch after
    every quit.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(128)
    return s


def _reserve_port(host: str) -> tuple[int, socket.socket]:
    """Claim the port we will serve on, and hold it.

    Reusing one port across launches is what keeps the webview origin stable;
    localStorage lives on the origin, so a different port means the onboarding
    flag, the chosen model and the lead agent all silently vanish and the app
    looks empty on launch. Returning the bound socket also closes the gap
    between checking a port and serving on it.
    """
    from .config import get_settings
    pf = get_settings().home / ".port"
    try:
        sock = _bind(host, int(pf.read_text().strip()))
    except Exception:
        sock = _bind(host, 0)        # genuinely taken (or never saved) → fresh one
    port = sock.getsockname()[1]
    with suppressed("pf.parent.mkdir(parents=True, exist_ok=True) …"):
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(port))
    return port, sock


def _install_edit_menu_now() -> None:
    """Main-thread half of `_install_edit_menu`.

    macOS delivers ⌘C, ⌘V, ⌘A and friends through the Edit menu's key
    equivalents, walking the responder chain until something answers. pywebview
    builds no menu bar at all, so there was no Edit menu, no key equivalents,
    and nothing answered: text in the conversation selected fine and then could
    not be copied, and the composer could not be pasted into.

    The items use the standard AppKit selectors with a nil target, which is
    what sends them down the responder chain to whatever has focus — the
    WKWebView for the conversation, the text field for the composer. A Python
    callback (what `webview.menu.MenuAction` offers) cannot do this: it takes
    no key equivalent, and it would have to guess which view to act on.
    """
    import AppKit

    app = AppKit.NSApplication.sharedApplication()
    main = app.mainMenu()
    if main is None:
        return
    for i in range(main.numberOfItems()):
        if main.itemAtIndex_(i).title() == "Edit":
            return                      # already there — do not add a second

    items = [
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        (None, None, None),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        (None, None, None),
        ("Select All", "selectAll:", "a"),
    ]
    edit = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    for title, selector, key in items:
        if title is None:
            edit.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, selector, key)
        edit.addItem_(item)

    holder = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
    holder.setSubmenu_(edit)
    main.addItem_(holder)


def _install_edit_menu() -> None:
    """Give the app an Edit menu once AppKit is up.

    Every Cocoa mutation in this app goes through AppHelper.callAfter: calling
    these setters off the main thread hangs the process, and pywebview runs
    this callback on a worker.
    """
    with suppressed("installing the Edit menu"):
        from PyObjCTools import AppHelper

        AppHelper.callAfter(_install_edit_menu_now)


def run_app(dev: bool = False) -> None:
    try:
        import webview
    except ImportError:
        raise SystemExit(
            "The desktop window needs pywebview. Install it with:\n"
            "    uv pip install -e '.[desktop]'   (or: pip install pywebview)\n"
            "Or run the browser version instead:  lodestone serve") from None

    from .config import get_settings

    get_settings()          # load settings / ensure the home dir exists

    # A sign-in the user walked away from leaves its CLI running forever. Clear
    # out anything a previous launch left behind before starting another.
    from .models import login_processes
    strays = login_processes.reap_all()
    if strays:
        print(f"Cleaned up {strays} unfinished sign-in "
              f"process{'es' if strays != 1 else ''} from a previous session.")

    host = "127.0.0.1"
    # Held until the server takes it over, so nothing can slip in between.
    port, sock = _reserve_port(host)

    server = None
    proc = None
    if dev:
        # Run the backend as a uvicorn subprocess with --reload so Python edits
        # hot-reload — then Cmd+R in the window picks up frontend + backend both.
        import subprocess
        import sys
        from pathlib import Path
        sock.close()             # the reloader subprocess binds it itself
        pkg = str(Path(__file__).resolve().parent)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "lodestone.api.app:app",
             "--host", host, "--port", str(port),
             "--reload", "--reload-dir", pkg, "--log-level", "warning"])
    else:
        import uvicorn

        from .api.app import app as fastapi_app
        config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        # Serve on the socket we already own rather than binding again — a second
        # bind can lose the port to whatever grabbed it in the meantime, and the
        # window would then load a stranger's server.
        threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True).start()

    if not _wait_for_port(host, port, timeout=30.0 if dev else 15.0):
        print("Lodestone server failed to start.")
        if proc:
            proc.terminate()
        return

    from . import hud

    class _AppBridge:
        """Reachable from the page as `window.pywebview.api`.

        The floating sign-in card is raised from here rather than from the API,
        because under --dev the backend is a separate process with no handle on
        the webview.
        """

        def open_signin_hud(self, provider: str, brand: str, auth_url: str = "") -> bool:
            return hud.open_signin(provider, brand, auth_url)

        def close_signin_hud(self) -> None:
            hud.close()

    window = webview.create_window(
        "Lodestone" + (" (dev)" if dev else ""),
        f"http://{host}:{port}",
        width=1280, height=860, min_size=(920, 620),
        js_api=_AppBridge(),
    )
    hud.configure(f"http://{host}:{port}", window)
    # Built now, on the main thread, and shown later from the page.
    hud.prepare(webview.create_window)

    try:
        # `func` runs once the GUI loop is up, which is the earliest point an
        # NSApplication exists to hang a menu on.
        webview.start(_install_edit_menu)   # blocks until the window is closed
    finally:
        # Quitting must not leave a login process waiting for a callback that
        # will never come — that is how 158 of them piled up on one machine.
        login_processes.reap_all()
        if server is not None:
            server.should_exit = True
        if proc is not None:
            proc.terminate()
