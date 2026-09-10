"""Data models for the memory brain — Brain v1.5."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"
    CONTEXTUAL = "contextual"
    COMMITMENT = "commitment"
    OBSERVATION = "observation"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    UNCERTAIN = "uncertain"
    DISPUTED = "disputed"
    EXPIRED = "expired"
    RETRACTED = "retracted"


class OpenLoopStatus(str, Enum):
    OPEN = "open"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STALE = "stale"


class OpenLoopPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


def map_kind_to_memory_type(kind: str) -> str:
    """Map legacy kinds to controlled Brain v1.5 memory types."""
    k = (kind or "").strip().lower()
    if k in ("preference", "pref"):
        return MemoryType.PREFERENCE.value
    if k in ("email", "message", "chat", "interaction", "event"):
        return MemoryType.EPISODIC.value
    if k in ("doc", "file", "fact", "note"):
        return MemoryType.SEMANTIC.value
    if k in ("procedure", "workflow", "rule", "instruction"):
        return MemoryType.PROCEDURAL.value
    if k in ("task", "todo", "commitment", "deadline"):
        return MemoryType.COMMITMENT.value
    if k in ("observation", "insight"):
        return MemoryType.OBSERVATION.value
    return MemoryType.SEMANTIC.value


class RecallExplanation(BaseModel):
    """Explainability metadata for retrieval scoring."""
    semantic_similarity: float = 0.0
    lexical_relevance: float = 0.0
    importance_boost: float = 0.0
    confidence_boost: float = 0.0
    recency_boost: float = 0.0
    temporal_boost: float = 0.0
    reinforcement_boost: float = 0.0
    source_boost: float = 0.0
    penalties: float = 0.0
    total_score: float = 0.0
    factors: list[str] = Field(default_factory=list)


class Memory(BaseModel):
    """A single unit of stored knowledge in Brain v1.5."""

    id: str
    text: str
    source: str = "manual"          # manual | files | gmail | notion | gdrive | agent | ...
    kind: str = "note"              # legacy compatibility field
    title: str | None = None
    uri: str | None = None          # location/reference

    # Brain v1.5 classification & provenance
    memory_type: str = "semantic"   # episodic | semantic | preference | procedural | contextual | commitment | observation
    source_id: str | None = None    # external unique id (message id, commit sha, etc.)
    extraction_method: str = "direct"  # direct | user_statement | llm_inference | heuristic | agent_observation
    evidence: str | None = None     # evidence snippet or provenance rationale

    # Brain v1.5 temporal dimension
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    event_date: str | None = None   # ISO YYYY-MM-DD
    event_time: str | None = None   # full ISO datetime
    valid_from: str | None = None   # when fact started being true
    valid_until: str | None = None  # when fact stopped being true (null = currently active)

    # Brain v1.5 confidence & importance
    importance: float = 0.5         # 0.0 to 1.0
    confidence: float = 0.8         # 0.0 to 1.0
    reinforcement_count: int = 0
    last_reinforced_at: str | None = None

    # Brain v1.5 access & activation tracking
    last_accessed_at: str | None = None
    access_count: int = 0

    # Brain v1.5 lifecycle state
    status: str = "active"          # active | superseded | uncertain | disputed | expired | retracted
    supersedes_id: str | None = None  # id of previous memory this replaced

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_valid_at(self, target_date: str | None = None) -> bool:
        """Check if memory was true at target_date (ISO YYYY-MM-DD or datetime)."""
        if not target_date:
            # check current validity
            return self.status == "active" and (self.valid_until is None)
        td = target_date[:10]
        if self.valid_from and self.valid_from[:10] > td:
            return False
        if self.valid_until and self.valid_until[:10] < td:
            return False
        return True

    def compute_activation(self, now_iso: str | None = None) -> float:
        """Non-destructive activation / decay score (0.0 to 1.0).
        Higher score means memory is active/reinforced/important, not forgotten."""
        import math
        ref = now_iso or _now()
        base = 0.4 * self.importance + 0.3 * self.confidence
        # reinforcement bonus
        r_bonus = min(0.2, self.reinforcement_count * 0.05)
        # access frequency bonus
        a_bonus = min(0.1, math.log1p(self.access_count) * 0.03)

        # recency decay factor (half-life of 90 days for inactive memories)
        last_touch = self.last_accessed_at or self.last_reinforced_at or self.updated_at or self.created_at
        try:
            d_then = datetime.fromisoformat(last_touch.replace("Z", "+00:00"))
            d_now = datetime.fromisoformat(ref.replace("Z", "+00:00"))
            days_ago = max(0.0, (d_now - d_then).total_seconds() / 86400.0)
            decay = math.exp(-days_ago / 180.0)  # smooth decay
        except Exception:
            decay = 0.8

        raw = (base + r_bonus + a_bonus) * (0.5 + 0.5 * decay)
        if self.status == "superseded":
            raw *= 0.35  # heavily downweight superseded in default activation
        elif self.status in ("disputed", "uncertain"):
            raw *= 0.70
        elif self.status == "retracted":
            raw = 0.0
        return round(min(1.0, max(0.0, raw)), 4)

    def as_context(self) -> str:
        """Render this memory the way it should be injected into an agent prompt."""
        head = self.title or self.memory_type.capitalize()
        status_tag = f" [{self.status.upper()}]" if self.status != "active" else ""
        date_tag = f" ({self.event_date or self.created_at[:10]})" if (self.event_date or self.created_at) else ""
        loc = f" · {self.uri}" if self.uri else ""
        conf_tag = f" (conf: {int(self.confidence * 100)}%)" if self.confidence < 0.7 else ""
        return f"[{self.source}:{head}{status_tag}]{date_tag}{loc}{conf_tag}\n{self.text.strip()}"


class RecallHit(BaseModel):
    memory: Memory
    score: float
    explanation: RecallExplanation | None = None


class OpenLoop(BaseModel):
    """An unfinished commitment, pending task, or follow-up loop."""

    id: str
    description: str
    status: str = "open"            # open | waiting | blocked | completed | cancelled | stale
    priority: str = "medium"        # low | medium | high | urgent
    confidence: float = 0.8         # 0.0 to 1.0
    due_at: str | None = None       # ISO date or datetime string
    source: str = "manual"          # manual | conversation | gmail | connector
    related_entities: list[str] = Field(default_factory=list)
    related_project: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_context(self) -> str:
        due = f" (due: {self.due_at})" if self.due_at else ""
        proj = f" [{self.related_project}]" if self.related_project else ""
        status_str = f" ({self.status})" if self.status != "open" else ""
        return f"- {self.description}{proj}{due}{status_str}"
