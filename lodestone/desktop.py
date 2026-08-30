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


def run_app() -> None:
    import uvicorn
    import webview

    from .api.app import app as fastapi_app
    from .config import get_settings

    s = get_settings()
    host, port = s.host, s.port

    config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_for_port(host, port):
        print("Lodestone server failed to start.")
        return

    webview.create_window(
        "Lodestone",
        f"http://{host}:{port}",
        width=1280, height=860, min_size=(920, 620),
    )
    try:
        webview.start()          # blocks until the window is closed
    finally:
        server.should_exit = True
