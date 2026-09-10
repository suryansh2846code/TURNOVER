"""Freshness: only TIME-SENSITIVE current claims decay. A confirmed historical
fact stays confirmed forever — we never lower confidence with age. What ages is
whether a *current* time-sensitive claim can still be trusted as current."""
from __future__ import annotations

from datetime import datetime, timezone

from .curate import TIME_SENSITIVE
from .store import CanonicalStore

AGING_DAYS = 30
STALE_DAYS = 90


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None


def compute(claim: dict) -> str:
    """fresh|aging|stale for one claim (read-time)."""
    if claim.get("type") not in TIME_SENSITIVE:
        return "fresh"
    if claim.get("state") not in ("current", "open"):
        return "fresh"
    age = _age_days(claim.get("last_confirmed_at") or claim.get("source_timestamp")
                    or claim.get("created_at"))
    if age is None:
        return "fresh"
    if age >= STALE_DAYS:
        return "stale"
    if age >= AGING_DAYS:
        return "aging"
    return "fresh"


def refresh_all(store: CanonicalStore) -> dict:
    """Maintenance pass: write freshness back for every current claim."""
    counts = {"fresh": 0, "aging": 0, "stale": 0}
    for c in store.current_claims():
        f = compute(c)
        counts[f] = counts.get(f, 0) + 1
        if c.get("freshness") != f:
            store.set_freshness(c["id"], f)
    return counts
