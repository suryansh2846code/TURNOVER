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


def _free_port(host: str) -> int:
    """Ask the OS for a free loopback port so the app never clashes."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _stable_port(host: str) -> int:
    """Reuse the same loopback port across launches so the webview keeps a stable
    origin — otherwise localStorage (onboarding flag, chosen model, lead agent…)
    resets on every launch. Falls back to a fresh free port if it's taken."""
    from .config import get_settings
    pf = get_settings().home / ".port"
    try:
        p = int(pf.read_text().strip())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, p))        # still free → reuse it
    except Exception:
        p = _free_port(host)
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(p))
    except Exception:
        pass
    return p


def run_app(dev: bool = False) -> None:
    try:
        import webview
    except ImportError:
        raise SystemExit(
            "The desktop window needs pywebview. Install it with:\n"
            "    uv pip install -e '.[desktop]'   (or: pip install pywebview)\n"
            "Or run the browser version instead:  lodestone serve")

    from .config import get_settings

    s = get_settings()
    host = "127.0.0.1"
    port = _stable_port(host)    # reuse a port across launches → stable webview origin

    server = None
    proc = None
    if dev:
        # Run the backend as a uvicorn subprocess with --reload so Python edits
        # hot-reload — then Cmd+R in the window picks up frontend + backend both.
        import subprocess
        import sys
        from pathlib import Path
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
        threading.Thread(target=server.run, daemon=True).start()

    if not _wait_for_port(host, port, timeout=30.0 if dev else 15.0):
        print("Lodestone server failed to start.")
        if proc:
            proc.terminate()
        return

    webview.create_window(
        "Lodestone" + (" (dev)" if dev else ""),
        f"http://{host}:{port}",
        width=1280, height=860, min_size=(920, 620),
    )
    try:
        webview.start()          # blocks until the window is closed
    finally:
        if server is not None:
            server.should_exit = True
        if proc is not None:
            proc.terminate()
