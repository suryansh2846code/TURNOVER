"""Base connector interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.store import MemoryStore, get_store


@dataclass
class SyncResult:
    connector: str
    added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "added": self.added,
            "skipped": self.skipped,
            "errors": self.errors,
            "detail": self.detail,
        }


class Connector:
    """A source of memories. Subclasses implement `sync`."""

    name: str = "base"
    label: str = "Base"
    #: True when the connector can run with no extra credentials/config.
    always_available: bool = False

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_store()

    def is_configured(self) -> tuple[bool, str]:
        """Return (ready, human-readable reason-if-not)."""
        return True, ""

    def sync(self, **kwargs: Any) -> SyncResult:  # pragma: no cover - interface
        raise NotImplementedError

    # helper for subclasses
    def _finish(self, result: SyncResult) -> SyncResult:
        self.store.set_connector_state(
            self.name,
            status="ok" if not result.errors else "error",
            detail=result.detail or f"+{result.added} added, {result.skipped} skipped",
            last_sync=datetime.now(timezone.utc).isoformat(),
        )
        return result
