"""The trust core: identity resolution, the review queue, and versioned
supersession. This is the only path that writes canonical truth.

Non-negotiable rules (enforced here, not left to the model):
  • Confirmed evidence can supersede inferred; inferred NEVER supersedes confirmed.
  • Replacing a current time-sensitive claim requires a NEWER source timestamp.
  • Tentative language creates an `open` claim/event — never a current fact.
  • Every accepted claim retains evidence.
  • Connector-sourced facts go to review; user self-disclosure is trusted.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .store import CanonicalStore, _norm

# Claim types where only ONE truth can be current at a time (a change supersedes
# the prior one). Everything else accumulates (many preferences, many decisions).
SINGULAR_TYPES = {"role", "project_status", "location", "availability",
                  "status", "next_step"}
# Time-sensitive claims whose replacement must have a newer source timestamp.
TIME_SENSITIVE = SINGULAR_TYPES | {"goal"}
# Sources we trust to write current truth without human review.
HIGH_TRUST = {"manual", "chat"}
# A confirmed claim/event of these types is worth a Timeline entry.
TIMELINE_TYPES = {"role", "project_status", "decision", "milestone"}


def _val_key(value: Any) -> str:
    return hashlib.sha256(_norm(str(value)).encode()).hexdigest()[:12]


def _claim_key(entity_id: str | None, ctype: str, value: Any) -> str:
    base = f"{entity_id or 'user'}:{ctype}"
    return base if ctype in SINGULAR_TYPES else f"{base}:{_val_key(value)}"


class Curator:
    def __init__(self, store: CanonicalStore | None = None) -> None:
        from .store import get_canonical_store
        self.store = store or get_canonical_store()

    # ── identity resolution ───────────────────────────────────────────────
    def resolve_entity(self, desc: dict, *, high_trust: bool) -> tuple[str | None, str]:
        """Return (entity_id | None, method). method ∈ exact|alias|created|review."""
        if not desc or not desc.get("name"):
            return None, "none"
        etype = desc.get("type", "person")
        # 1) stable identifiers win
        for ident in desc.get("identifiers", []) or []:
            kind, value = ident.get("kind"), ident.get("value")
            if kind in ("email", "github_login", "gmail_contact_id") and value:
                eid = self.store.entity_for_identifier(kind, value)
                if eid:
                    return eid, "exact"
        # 2) exact canonical-name match of the same type = alias
        existing = self.store.entity_by_name(etype, desc["name"])
        if existing:
            return existing["id"], "alias"
        # 3) new. Create only if we have a stable id OR it's a user-trusted,
        #    non-person entity (projects/orgs the user names directly). A brand
        #    new PERSON with no stable identifier is ambiguous → review.
        has_id = any(i.get("kind") in ("email", "github_login", "gmail_contact_id")
                     for i in (desc.get("identifiers") or []))
        if has_id or (high_trust and etype != "person"):
            eid = self.store.create_entity(etype, desc["name"])
            for ident in desc.get("identifiers", []) or []:
                if ident.get("kind") and ident.get("value"):
                    self.store.add_identifier(eid, ident["kind"], ident["value"])
            return eid, "created"
        return None, "review"

    # ── applying one candidate ────────────────────────────────────────────
    def apply_candidate(self, cand: dict, *, source_type: str,
                        source_uri: str | None = None,
                        source_timestamp: str | None = None,
                        force: bool = False) -> dict:
        """Apply a candidate to canonical truth, or enqueue it for review.
        `force=True` means a human already approved it (skip the trust gate)."""
        high_trust = force or source_type in HIGH_TRUST
        kind = cand.get("kind")
        if kind == "claim":
            return self._apply_claim(cand, source_type, source_uri,
                                     source_timestamp, high_trust, force)
        if kind == "event":
            return self._apply_event(cand, source_type, source_uri, source_timestamp)
        if kind == "task":
            return self._apply_task(cand, source_type, source_uri, source_timestamp)
        return {"outcome": "ignored", "reason": f"unknown kind {kind}"}

    def _resolve_for_claim(self, cand, high_trust):
        entity_id, method = None, "none"
        if cand.get("entity"):
            entity_id, method = self.resolve_entity(cand["entity"], high_trust=high_trust)
        return entity_id, method

    def _apply_claim(self, cand, source_type, source_uri, source_timestamp,
                     high_trust, force) -> dict:
        entity_id, method = self._resolve_for_claim(cand, high_trust)
        tentative = bool(cand.get("tentative"))
        confidence = "inferred" if tentative else cand.get("confidence", "inferred")
        section = cand.get("section", "about_you")
        ctype = cand.get("type", "preference")
        value = cand.get("value")
        if not value:
            return {"outcome": "ignored", "reason": "empty value"}

        # Gate: uncertain identity or low-trust inferred → review queue.
        if not force:
            if method == "review":
                return self._queue(cand, source_type, source_uri,
                                   "uncertain person identity")
            if confidence == "inferred" and not tentative and source_type not in HIGH_TRUST:
                return self._queue(cand, source_type, source_uri,
                                   "inferred fact from connector — needs review")

        key = _claim_key(entity_id, ctype, value)
        existing = self.store.current_claim_by_key(key)

        # New, tentative → an `open` claim (never current).
        state = "open" if tentative else "current"

        if existing is None:
            cid = self.store.insert_claim(
                entity_id=entity_id, section=section, type=ctype, value=value,
                state=state, confidence=confidence,
                source_timestamp=source_timestamp, claim_key=key)
            self._evidence(cid, None, cand, source_type, source_uri)
            if state == "current" and confidence == "confirmed" and ctype in TIMELINE_TYPES:
                self._timeline_change(entity_id, f"New {ctype}: {value}",
                                      source_timestamp)
            return {"outcome": "added", "claim_id": cid, "state": state,
                    "entity_id": entity_id}

        # Same value restated → re-confirm (freshness), no new version.
        if _norm(str(existing["value"])) == _norm(str(value)):
            self.store.touch_claim(existing["id"], source_timestamp)
            self._evidence(existing["id"], None, cand, source_type, source_uri)
            return {"outcome": "reconfirmed", "claim_id": existing["id"]}

        # Different value → decide supersession.
        # Tentative alternatives never disturb the current truth.
        if tentative:
            cid = self.store.insert_claim(
                entity_id=entity_id, section=section, type=ctype, value=value,
                state="open", confidence="inferred",
                source_timestamp=source_timestamp, claim_key=key + ":alt")
            self._evidence(cid, None, cand, source_type, source_uri)
            return {"outcome": "added_open", "claim_id": cid}

        # inferred may not overwrite confirmed truth.
        if confidence == "inferred" and existing["confidence"] == "confirmed" and not force:
            return self._queue(cand, source_type, source_uri,
                               "would override a confirmed fact — needs review")

        # time-sensitive claims need a newer source timestamp to replace.
        if ctype in TIME_SENSITIVE and existing.get("source_timestamp") and \
                source_timestamp and source_timestamp <= existing["source_timestamp"] \
                and not force:
            return {"outcome": "ignored", "reason": "older than current claim"}

        # Supersede: retire the old, append the new, record the change.
        self.store.supersede_claim(existing["id"])
        cid = self.store.insert_claim(
            entity_id=entity_id, section=section, type=ctype, value=value,
            state="current", confidence=confidence,
            source_timestamp=source_timestamp, claim_key=key,
            supersedes=existing["id"])
        self._evidence(cid, None, cand, source_type, source_uri)
        self._timeline_change(
            entity_id, f"{ctype} changed: “{existing['value']}” → “{value}”",
            source_timestamp)
        return {"outcome": "superseded", "claim_id": cid,
                "superseded": existing["id"]}

    def _apply_event(self, cand, source_type, source_uri, source_timestamp) -> dict:
        occurred = cand.get("occurred_at") or (source_timestamp or "")[:10]
        summary = cand.get("summary")
        etype = cand.get("event_type", "interaction")
        if not summary or not occurred:
            return {"outcome": "ignored", "reason": "event missing date/summary"}
        entity_id, _ = (self.resolve_entity(cand["entity"], high_trust=True)
                        if cand.get("entity") else (None, "none"))
        if self.store.event_exists(etype, occurred, summary):
            return {"outcome": "duplicate_event"}
        eid = self.store.add_event(event_type=etype, occurred_at=occurred,
                                   summary=summary, entity_id=entity_id,
                                   source_timestamp=source_timestamp)
        self._evidence(None, eid, cand, source_type, source_uri)
        return {"outcome": "event_added", "event_id": eid}

    def _apply_task(self, cand, source_type, source_uri, source_timestamp) -> dict:
        title = cand.get("title")
        if not title:
            return {"outcome": "ignored", "reason": "task missing title"}
        entity_id, _ = (self.resolve_entity(cand["entity"], high_trust=True)
                        if cand.get("entity") else (None, "none"))
        state = "open"
        if cand.get("tentative"):
            state = "open"
        tid = self.store.upsert_task(
            title=title, owner=cand.get("owner", "user"), state=state,
            due_at=cand.get("due_at"), entity_id=entity_id,
            source_timestamp=source_timestamp)
        return {"outcome": "task_upserted", "task_id": tid}

    # ── helpers ───────────────────────────────────────────────────────────
    def _evidence(self, claim_id, event_id, cand, source_type, source_uri):
        self.store.add_evidence(
            claim_id=claim_id, event_id=event_id, source_type=source_type,
            source_uri=source_uri, excerpt=cand.get("evidence_excerpt"))

    def _timeline_change(self, entity_id, summary, source_timestamp):
        from datetime import datetime, timezone
        occurred = (source_timestamp or datetime.now(timezone.utc).isoformat())[:10]
        if not self.store.event_exists("change", occurred, summary):
            self.store.add_event(event_type="change", occurred_at=occurred,
                                 summary=summary, entity_id=entity_id,
                                 source_timestamp=source_timestamp)

    def _queue(self, cand, source_type, source_uri, reason) -> dict:
        cid = self.store.add_candidate(
            kind=cand.get("kind", "claim"), payload=cand, status="needs_review",
            reason=reason, source_type=source_type, source_uri=source_uri)
        return {"outcome": "queued", "candidate_id": cid, "reason": reason}

    # ── review-queue actions ──────────────────────────────────────────────
    def approve(self, candidate_id: str) -> dict:
        cand = self.store.get_candidate(candidate_id)
        if not cand or cand["status"] not in ("pending", "needs_review"):
            return {"outcome": "ignored", "reason": "not pending"}
        res = self.apply_candidate(
            cand["payload"], source_type=cand.get("source_type") or "manual",
            source_uri=cand.get("source_uri"),
            source_timestamp=cand["payload"].get("source_timestamp"),
            force=True)
        self.store.set_candidate_status(candidate_id, "approved")
        return res

    def reject(self, candidate_id: str, reason: str = "") -> dict:
        self.store.set_candidate_status(candidate_id, "rejected", reason)
        return {"outcome": "rejected"}
