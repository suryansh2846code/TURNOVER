"""Data models for the memory brain."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory(BaseModel):
    """A single unit of stored knowledge."""

    id: str
    text: str
    source: str = "manual"          # manual | files | gmail | notion | gdrive | agent
    kind: str = "note"              # note | fact | email | doc | message | preference
    title: str | None = None
    uri: str | None = None          # where it came from (file path, url, message id)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_context(self) -> str:
        """Render this memory the way it should be injected into a prompt."""
        head = self.title or self.kind.capitalize()
        loc = f" ({self.uri})" if self.uri else ""
        return f"[{self.source}:{head}]{loc}\n{self.text.strip()}"


class RecallHit(BaseModel):
    memory: Memory
    score: float
