"""CanonicalBrain — the facade the app talks to. Ties extraction, redaction,
the curator, recall, freshness, export and evaluation together, and owns the
first-build Gmail curation + ongoing conversation learning.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import evaluation, export as _export, extract, freshness, recall, redact
from .curate import Curator
from .store import CanonicalStore, get_canonical_store


def _provider_or_none(provider_name=None, model_name=None):
    try:
        from ...config import get_settings
        from ...models.registry import get_provider
        return get_provider(provider_name or get_settings().model_provider, model_name)
    except Exception:
        return None


class CanonicalBrain:
    def __init__(self, store: CanonicalStore | None = None) -> None:
        self.store = store or get_canonical_store()
        self.curator = Curator(self.store)

    # ── the write path: any text → candidates → trust rules ───────────────
    def learn_from_text(self, text: str, *, source_type: str,
                        source_uri: str | None = None,
                        source_timestamp: str | None = None,
                        actor: str = "user", provider=None,
                        provider_name=None, model_name=None) -> dict:
        """Redact → extract → curate. The single entry point for growing the
        canonical Brain from ANY source (chat, email, manual, connector)."""
        if not text or not text.strip():
            return {"outcomes": [], "skipped": "empty"}
        if redact.is_sensitive(text):
            return {"outcomes": [], "skipped": "sensitive"}
        clean = redact.redact(text)
        if provider is None:
            provider = _provider_or_none(provider_name, model_name)
        cands = extract.extract_candidates(
            clean, provider, actor=actor, event_date=(source_timestamp or "")[:10] or None)
        outcomes = []
        for c in cands:
            c.setdefault("source_timestamp", source_timestamp)
            res = self.curator.apply_candidate(
                c, source_type=source_type, source_uri=source_uri,
                source_timestamp=source_timestamp)
            outcomes.append({"kind": c.get("kind"), **res})
        return {"outcomes": outcomes,
                "added": sum(1 for o in outcomes if o.get("outcome") in
                             ("added", "superseded", "event_added", "task_upserted")),
                "queued": sum(1 for o in outcomes if o.get("outcome") == "queued")}

    def learn_from_conversation(self, user_text: str, assistant_text: str = "",
                                *, provider=None, provider_name=None,
                                model_name=None) -> dict:
        """Grow the Brain from an ongoing chat turn. User self-disclosure is
        trusted (source_type='chat'); we do NOT mine the assistant's own words
        as fact about the user."""
        from datetime import datetime, timezone
        return self.learn_from_text(
            user_text, source_type="chat", source_uri="chat://turn",
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            actor="user", provider=provider, provider_name=provider_name,
            model_name=model_name)

    def remember(self, text: str, *, provider=None, **kw) -> dict:
        """Explicit 'remember this' — highest trust (source_type='manual')."""
        from datetime import datetime, timezone
        return self.learn_from_text(
            text, source_type="manual", source_uri="manual://note",
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            actor="user", provider=provider, **kw)

    # ── first-build Gmail curation (metadata-first, bounded body) ──────────
    def rank_threads(self, messages: list[dict]) -> list[dict]:
        """Structural ranking (NOT keyword-first). Each message dict may carry:
        from_me, is_reply, labels, thread_size, sender, has_event, unread."""
        ranked = []
        for m in messages:
            ranked.append({**m, "_score": _thread_score(m)})
        ranked.sort(key=lambda m: m["_score"], reverse=True)
        return ranked

    def first_build_from_messages(self, messages: list[dict], *, top: int = 40,
                                  provider=None, provider_name=None,
                                  model_name=None) -> dict:
        """Rank all metadata, read bodies only for the top-N, extract candidates.
        `messages` must include a 'body' for the high-signal ones (or this reads
        the provided body). Connector-sourced → everything routes via review."""
        if provider is None:
            provider = _provider_or_none(provider_name, model_name)
        ranked = self.rank_threads(messages)
        processed = 0
        summary = {"added": 0, "queued": 0, "skipped": 0}
        for m in ranked[:top]:
            body = m.get("body") or ""
            if not body:
                summary["skipped"] += 1
                continue
            res = self.learn_from_text(
                body, source_type="gmail",
                source_uri=m.get("uri") or f"gmail://{m.get('id','')}",
                source_timestamp=m.get("date"), actor="external",
                provider=provider)
            summary["added"] += res.get("added", 0)
            summary["queued"] += res.get("queued", 0)
            processed += 1
        summary["processed"] = processed
        summary["ranked"] = len(ranked)
        return summary

    # ── read path ─────────────────────────────────────────────────────────
    def recall_block(self, query: str, **kw) -> dict:
        return recall.build_block(self.store, query, **kw)

    # ── review queue ──────────────────────────────────────────────────────
    def pending(self, limit: int = 100) -> list[dict]:
        return self.store.pending_candidates(limit)

    def approve(self, candidate_id: str) -> dict:
        return self.curator.approve(candidate_id)

    def reject(self, candidate_id: str, reason: str = "") -> dict:
        return self.curator.reject(candidate_id, reason)

    # ── views ─────────────────────────────────────────────────────────────
    def about_you(self) -> list[dict]:
        return [self._with_fresh(c)
                for c in self.store.current_claims(entity_id=None, section="about_you")]

    def people(self) -> list[dict]:
        return self._entities("person")

    def work(self) -> list[dict]:
        return self._entities("project") + self._entities("organization")

    def timeline(self, limit: int = 200) -> list[dict]:
        return self.store.timeline(limit)

    def _entities(self, etype: str) -> list[dict]:
        out = []
        for e in self.store.list_entities(type=etype):
            out.append({**e,
                        "claims": [self._with_fresh(c)
                                   for c in self.store.current_claims(entity_id=e["id"])],
                        "tasks": self.store.open_tasks(entity_id=e["id"]),
                        "identifiers": self.store.identifiers_for(e["id"])})
        return out

    def _with_fresh(self, c: dict) -> dict:
        c = dict(c)
        c["freshness"] = freshness.compute(c)
        c["evidence"] = self.store.evidence_for_claim(c["id"])
        return c

    # ── maintenance & ops ─────────────────────────────────────────────────
    def maintain(self) -> dict:
        return {"freshness": freshness.refresh_all(self.store)}

    def export(self, out_dir=None) -> dict:
        return _export.export(self.store, out_dir)

    def evaluate(self, k: int = 5) -> dict:
        return evaluation.run(self.store, k=k)

    def add_eval_case(self, **kw) -> str:
        return self.store.add_eval_case(**kw)

    def stats(self) -> dict:
        return self.store.stats()

    def reset(self) -> dict:
        self.store.wipe()
        return {"reset": True}


# ── structural thread scoring ─────────────────────────────────────────────
_NONHUMAN = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|mailer|bounce|"
    r"newsletter|updates?@|support@|team@|hello@|info@|billing@)", re.I)


def _is_human(sender: str | None) -> bool:
    return bool(sender) and not _NONHUMAN.search(sender)


def _thread_score(m: dict) -> int:
    s = 0
    labels = {str(x).upper() for x in (m.get("labels") or [])}
    if m.get("from_me"):
        s += 3
    if m.get("is_reply"):
        s += 3
    if "IMPORTANT" in labels:
        s += 2
    if "STARRED" in labels:
        s += 2
    if "CATEGORY_PERSONAL" in labels:
        s += 2
    if labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}:
        s -= 4
    s += min(int(m.get("thread_size") or 1), 5)
    if _is_human(m.get("sender")):
        s += 2
    if m.get("has_event"):
        s += 2
    if m.get("unread"):
        s += 1
    return s


@lru_cache
def get_canonical() -> CanonicalBrain:
    return CanonicalBrain()
