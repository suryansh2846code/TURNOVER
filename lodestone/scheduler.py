"""Continuous background sync — keeps the brain current on a timer.

A daemon thread periodically re-syncs every *ready* connector (no browser),
mirroring Turnstone's "continuously updates". Re-syncs are cheap because the
store skips content it already has (no re-embedding of unchanged items).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import get_settings
from .connectors import REGISTRY, get_connector
from .connectors.files import FilesConnector

# app connectors that can sync with defaults once configured (no user input)
_AUTO = ["gmail", "gcal", "gdrive", "notion", "imessage"]


class Scheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sync_lock = threading.Lock()
        self.last_run: str | None = None
        self.last_result: dict[str, Any] = {}
        self.running = False
        self.syncing = False

    # ── one sweep over all ready connectors ──────────────────────────────
    def sync_all(self, interactive: bool = False) -> dict[str, Any]:
        if not self._sync_lock.acquire(blocking=False):
            return {"skipped": "a sync is already running"}
        try:
            self.syncing = True
            return self._sync_all(interactive)
        finally:
            self.syncing = False
            self._sync_lock.release()

    def _sync_all(self, interactive: bool) -> dict[str, Any]:
        from .core.store import get_store
        store = get_store()
        summary: dict[str, Any] = {}

        # app-based connectors
        for name in _AUTO:
            cls = REGISTRY.get(name)
            if not cls:
                continue
            inst = cls()
            ready, _ = inst.is_configured()
            if not ready:
                continue
            try:
                res = inst.sync(interactive=interactive)
                summary[name] = {"added": res.added, "errors": res.errors[:1]}
            except Exception as exc:
                summary[name] = {"added": 0, "errors": [str(exc)[:120]]}

        # local files: re-index remembered folders
        for path in FilesConnector.synced_paths(store):
            try:
                res = get_connector("files").sync(path=path)
                key = f"files:{path.split('/')[-1]}"
                summary[key] = {"added": res.added, "errors": res.errors[:1]}
            except Exception as exc:
                summary[f"files:{path}"] = {"added": 0, "errors": [str(exc)[:120]]}

        self.last_run = datetime.now(timezone.utc).isoformat()
        self.last_result = summary
        return summary

    # ── background loop ──────────────────────────────────────────────────
    def _loop(self) -> None:
        settings = get_settings()
        interval = max(1, settings.sync_interval_minutes) * 60
        # small initial delay so startup isn't blocked
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                self.sync_all(interactive=False)
            except Exception:
                pass
            if self._stop.wait(interval):
                return

    def start(self) -> None:
        settings = get_settings()
        if not settings.sync_enabled or self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False


_scheduler = Scheduler()


def get_scheduler() -> Scheduler:
    return _scheduler
