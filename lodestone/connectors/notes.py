"""Manual notes connector — direct user-entered facts/preferences."""
from __future__ import annotations

from typing import Any

from .base import Connector, SyncResult


class NotesConnector(Connector):
    name = "notes"
    label = "Manual Notes"
    always_available = True

    def sync(self, *, text: str = "", title: str | None = None,
             kind: str = "note", tags: list[str] | None = None,
             **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        mem = self.store.add(
            text=text, source=self.name, kind=kind, title=title, tags=tags or []
        )
        if mem:
            result.added = 1
            result.detail = f"stored note {mem.id[:8]}"
        else:
            result.skipped = 1
            result.detail = "empty or duplicate note"
        return self._finish(result)
