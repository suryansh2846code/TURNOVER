"""Lightweight contradiction detection and resolution for Brain v1.5.

Identifies conflicting preferences, changed states, and opposing statements.
Preserves historical records by superseding or disputing rather than deleting.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..core.models import Memory, MemoryStatus


_PREF_PATTERNS = [
    re.compile(r"\b(?:prefer|likes?|loves?|favor|uses?|chose|switched to)\s+([A-Za-z0-9#+.-]+)", re.I),
    re.compile(r"\b(?:moving away from|stopped using|hate|dislike|no longer use|dropped)\s+([A-Za-z0-9#+.-]+)", re.I),
]

_OPPOSING_CUES = [
    (re.compile(r"\b(?:prefers?|likes?|uses?)\s+([A-Za-z0-9#+.-]+)", re.I),
     re.compile(r"\b(?:moving away from|stopped using|dislikes?|no longer uses?)\s+([A-Za-z0-9#+.-]+)", re.I)),
]


def detect_conflicts(memories: list[Memory]) -> list[dict[str, Any]]:
    """Scan active memories for contradictions (e.g. opposing preferences)."""
    active_mems = [m for m in memories if m.status == MemoryStatus.ACTIVE.value]
    conflicts: list[dict[str, Any]] = []

    # Check pairwise within same or similar subjects
    n = len(active_mems)
    for i in range(n):
        for j in range(i + 1, n):
            m1 = active_mems[i]
            m2 = active_mems[j]

            # 1. Direct opposing statements (e.g. "I use React" vs "moving away from React")
            c = _check_direct_opposition(m1, m2)
            if c:
                conflicts.append(c)
                continue

            # 2. Singular preference category clash (e.g. "prefers dark mode" vs "prefers light mode")
            c2 = _check_category_clash(m1, m2)
            if c2:
                conflicts.append(c2)

    return conflicts


def _check_direct_opposition(m1: Memory, m2: Memory) -> dict[str, Any] | None:
    t1 = m1.text.lower()
    t2 = m2.text.lower()

    for pos_pat, neg_pat in _OPPOSING_CUES:
        m_pos1 = pos_pat.search(t1)
        m_neg2 = neg_pat.search(t2)
        if m_pos1 and m_neg2:
            target1 = m_pos1.group(1).lower()
            target2 = m_neg2.group(1).lower()
            if target1 == target2 or target1 in target2 or target2 in target1:
                return _build_conflict_dict(m1, m2, target1, "direct_negation")

        m_neg1 = neg_pat.search(t1)
        m_pos2 = pos_pat.search(t2)
        if m_neg1 and m_pos2:
            target1 = m_neg1.group(1).lower()
            target2 = m_pos2.group(1).lower()
            if target1 == target2 or target1 in target2 or target2 in target1:
                return _build_conflict_dict(m2, m1, target1, "direct_negation")

    return None


def _check_category_clash(m1: Memory, m2: Memory) -> dict[str, Any] | None:
    """Check if both express mutually exclusive preferences in the same domain."""
    t1 = m1.text.lower()
    t2 = m2.text.lower()

    pairs = [
        ("dark mode", "light mode"),
        ("tabs", "spaces"),
        ("remote", "in-office"),
        ("mac", "windows"),
        ("python", "ruby"),
    ]

    for a, b in pairs:
        if (a in t1 and b in t2) or (b in t1 and a in t2):
            if any(w in t1 for w in ("prefer", "use", "like")) and any(w in t2 for w in ("prefer", "use", "like")):
                return _build_conflict_dict(m1, m2, f"{a} vs {b}", "mutually_exclusive")

    return None


def _build_conflict_dict(m1: Memory, m2: Memory, topic: str, nature: str) -> dict[str, Any]:
    # Determine which is newer
    d1 = m1.event_date or m1.created_at
    d2 = m2.event_date or m2.created_at

    if d2 > d1:
        newer, older = m2, m1
    else:
        newer, older = m1, m2

    # Confidence comparison
    can_auto_supersede = newer.confidence >= older.confidence and (d2 != d1)

    return {
        "topic": topic,
        "nature": nature,
        "older_id": older.id,
        "newer_id": newer.id,
        "older_text": older.text,
        "newer_text": newer.text,
        "older_confidence": older.confidence,
        "newer_confidence": newer.confidence,
        "recommendation": "supersede_older" if can_auto_supersede else "mark_disputed",
    }


def resolve_conflict(store, conflict: dict[str, Any], auto_supersede: bool = True) -> dict[str, Any]:
    """Resolve a detected conflict non-destructively in MemoryStore."""
    older_id = conflict["older_id"]
    newer_id = conflict["newer_id"]

    if conflict.get("recommendation") == "supersede_older" and auto_supersede:
        store.supersede(older_id, newer_id)
        return {"action": "superseded", "superseded_id": older_id, "active_id": newer_id}
    else:
        store.update_status(older_id, MemoryStatus.DISPUTED.value)
        return {"action": "disputed", "disputed_id": older_id, "active_id": newer_id}
