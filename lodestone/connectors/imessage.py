"""iMessage connector — ingests recent messages from the local macOS chat.db.

Fully local, no auth — but macOS requires the running app (Terminal/Python) to
have Full Disk Access to read ~/Library/Messages/chat.db.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import Connector, SyncResult

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
# Apple stores message dates as ns since 2001-01-01; convert to epoch seconds.
APPLE_EPOCH = 978307200


class IMessageConnector(Connector):
    name = "imessage"
    label = "iMessage"

    def is_configured(self) -> tuple[bool, str]:
        if not CHAT_DB.exists():
            return False, "no Messages database (macOS only)"
        try:
            con = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            con.execute("SELECT 1 FROM message LIMIT 1")
            con.close()
            return True, ""
        except Exception:
            return False, ("grant Full Disk Access to your terminal/app "
                           "(System Settings → Privacy & Security → Full Disk Access)")

    def sync(self, *, days: int = 90, max_messages: int = 1500,
             min_thread: int = 3, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        ready, reason = self.is_configured()
        if not ready:
            result.errors.append(reason)
            return self._finish(result)
        try:
            con = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            cutoff_ns = (self._now_epoch() - days * 86400 - APPLE_EPOCH) * 1_000_000_000
            rows = con.execute(
                """
                SELECT h.id AS handle, m.text AS text, m.is_from_me AS mine,
                       m.date AS date
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.text IS NOT NULL AND m.text != '' AND m.date > ?
                ORDER BY m.date ASC
                LIMIT ?
                """,
                (cutoff_ns, max_messages * 3),
            ).fetchall()
            con.close()

            # group into per-contact threads, keep meaningful ones
            threads: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                who = "Me" if r["mine"] else (r["handle"] or "Them")
                threads[r["handle"] or "unknown"].append(f"{who}: {r['text']}")

            from ..brain import get_brain
            brain = get_brain()
            for handle, msgs in threads.items():
                if len(msgs) < min_thread:
                    continue
                text = f"iMessage thread with {handle}:\n" + "\n".join(msgs[-60:])
                out = brain.ingest(
                    text, source=self.name, kind="message",
                    title=f"Messages with {handle}", fast=True,
                    metadata={"handle": handle, "count": len(msgs)},
                )
                result.added += out["memories"]
            result.detail = f"{len(threads)} conversations, last {days}d"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)

    def _now_epoch(self) -> int:
        import time
        return int(time.time())
