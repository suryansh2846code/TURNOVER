"""Desktop app — run Lodestone as a native window instead of a browser tab.

Starts the FastAPI server in a background thread and shows the UI in a native
webview window. `lodestone app` launches it; the macOS .app bundle calls the
same entry point.
"""
from __future__ import annotations

import socket
import threading
import time


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
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(port))
    except Exception:
        pass
    return port, sock


def run_app(dev: bool = False) -> None:
    try:
        import webview
    except ImportError:
        raise SystemExit(
            "The desktop window needs pywebview. Install it with:\n"
            "    uv pip install -e '.[desktop]'   (or: pip install pywebview)\n"
            "Or run the browser version instead:  lodestone serve")

    from .config import get_settings

    get_settings()          # load settings / ensure the home dir exists
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
        webview.start()          # blocks until the window is closed
    finally:
        if server is not None:
            server.should_exit = True
        if proc is not None:
            proc.terminate()
