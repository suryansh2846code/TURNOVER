"""Tests for the canonical Brain: trust rules, supersession, identity,
redaction, freshness, recall ordering, evaluation, export."""
from __future__ import annotations

import pytest

from lodestone.brain.canonical import freshness, redact
from lodestone.brain.canonical.service import CanonicalBrain
from lodestone.brain.canonical.store import CanonicalStore


class MockProvider:
    """Forces the offline heuristic extraction path."""
    name = "mock"
    model = "mock"
    def is_ready(self):
        return True, ""


@pytest.fixture
def cb(tmp_path):
    store = CanonicalStore(db_path=tmp_path / "brain.db")
    return CanonicalBrain(store=store)


def _claim(section="about_you", type="preference", value="likes local-first tools",
           confidence="confirmed", tentative=False, entity=None, ts=None):
    return {"kind": "claim", "section": section, "type": type, "value": value,
            "confidence": confidence, "tentative": tentative, "entity": entity,
            "evidence_excerpt": value, "source_timestamp": ts}


# ── redaction ──────────────────────────────────────────────────────────────
def test_redact_masks_secrets():
    out = redact.redact("my api key is sk-abcdefghijklmnop1234 ok")
    assert "sk-abcdefghijklmnop1234" not in out
    assert "REDACTED" in out

def test_redact_otp_and_password():
    assert "REDACTED" in redact.redact("your OTP is 483920")
    assert "hunter2" not in redact.redact("password: hunter2")

def test_sensitive_notifications_dropped(cb):
    res = cb.learn_from_text("Please reset your password using this link",
                             source_type="gmail", provider=MockProvider())
    assert res["skipped"] == "sensitive"


# ── basic curation from self-disclosure ─────────────────────────────────────
def test_self_disclosure_becomes_confirmed_about_you(cb):
    res = cb.learn_from_conversation("I prefer local-first tools and I use Ollama.",
                                     provider=MockProvider())
    assert res["added"] >= 1
    facts = cb.about_you()
    assert facts and all(f["confidence"] == "confirmed" for f in facts)
    # evidence retained
    assert all(cb.store.evidence_for_claim(f["id"]) for f in facts)


# ── supersession ────────────────────────────────────────────────────────────
def test_singular_claim_supersedes_with_newer_timestamp(cb):
    r1 = cb.curator.apply_candidate(
        _claim(type="role", value="founder", ts="2026-01-01"),
        source_type="chat", source_timestamp="2026-01-01")
    assert r1["outcome"] == "added"
    r2 = cb.curator.apply_candidate(
        _claim(type="role", value="engineer", ts="2026-06-01"),
        source_type="chat", source_timestamp="2026-06-01")
    assert r2["outcome"] == "superseded"
    current = cb.store.current_claims(entity_id=None)
    roles = [c for c in current if c["type"] == "role"]
    assert len(roles) == 1 and roles[0]["value"] == "engineer"
    # old one is historical
    old = cb.store.get_claim(r1["claim_id"])
    assert old["state"] == "historical"
    # a timeline change event was recorded
    assert any("changed" in e["summary"] for e in cb.store.timeline())

def test_older_timestamp_does_not_replace_current(cb):
    cb.curator.apply_candidate(_claim(type="role", value="engineer", ts="2026-06-01"),
                               source_type="chat", source_timestamp="2026-06-01")
    r = cb.curator.apply_candidate(_claim(type="role", value="intern", ts="2026-01-01"),
                                   source_type="chat", source_timestamp="2026-01-01")
    assert r["outcome"] == "ignored"

def test_inferred_never_supersedes_confirmed(cb):
    cb.curator.apply_candidate(_claim(type="role", value="founder", ts="2026-01-01"),
                               source_type="chat", source_timestamp="2026-01-01")
    r = cb.curator.apply_candidate(
        _claim(type="role", value="student", confidence="inferred", ts="2026-06-01"),
        source_type="chat", source_timestamp="2026-06-01")
    assert r["outcome"] == "queued"
    # current truth untouched
    roles = [c for c in cb.store.current_claims(entity_id=None) if c["type"] == "role"]
    assert roles[0]["value"] == "founder"

def test_restated_fact_is_reconfirmed_not_duplicated(cb):
    r1 = cb.curator.apply_candidate(_claim(type="role", value="founder", ts="2026-01-01"),
                                    source_type="chat", source_timestamp="2026-01-01")
    r2 = cb.curator.apply_candidate(_claim(type="role", value="Founder", ts="2026-02-01"),
                                    source_type="chat", source_timestamp="2026-02-01")
    assert r2["outcome"] == "reconfirmed"
    assert r2["claim_id"] == r1["claim_id"]


# ── tentative handling ──────────────────────────────────────────────────────
def test_tentative_creates_open_claim_not_current(cb):
    r = cb.curator.apply_candidate(
        _claim(type="project_status", value="maybe launch next week", tentative=True),
        source_type="chat")
    assert r["state"] == "open"
    opens = [c for c in cb.store.current_claims() if c["state"] == "open"]
    assert opens and opens[0]["value"] == "maybe launch next week"

def test_tentative_does_not_disturb_current(cb):
    cb.curator.apply_candidate(_claim(type="project_status", value="shipped v1", ts="2026-05-01"),
                               source_type="chat", source_timestamp="2026-05-01")
    cb.curator.apply_candidate(
        _claim(type="project_status", value="maybe pivot", tentative=True, ts="2026-06-01"),
        source_type="chat", source_timestamp="2026-06-01")
    current = [c for c in cb.store.current_claims() if c["state"] == "current"
               and c["type"] == "project_status"]
    assert len(current) == 1 and current[0]["value"] == "shipped v1"


# ── identity resolution ─────────────────────────────────────────────────────
def test_identity_resolves_by_email_across_names(cb):
    ent = {"type": "person", "name": "Jai",
           "identifiers": [{"kind": "email", "value": "jai@turnstone.ai"}]}
    r1 = cb.curator.apply_candidate(
        _claim(section="people", type="role", value="Turnstone founder", entity=ent),
        source_type="chat")
    ent2 = {"type": "person", "name": "Jai Bhatia",
            "identifiers": [{"kind": "email", "value": "jai@turnstone.ai"}]}
    r2 = cb.curator.apply_candidate(
        _claim(section="people", type="preference", value="prefers async", entity=ent2),
        source_type="chat")
    assert r1["entity_id"] == r2["entity_id"]
    assert len(cb.store.list_entities(type="person")) == 1

def test_unknown_person_no_id_goes_to_review(cb):
    ent = {"type": "person", "name": "Some Person"}  # no stable id
    r = cb.curator.apply_candidate(
        _claim(section="people", type="role", value="a contact", entity=ent,
               confidence="inferred"),
        source_type="gmail")
    assert r["outcome"] == "queued"
    assert cb.pending()  # sitting in review queue


# ── review queue round-trip ─────────────────────────────────────────────────
def test_review_approve_promotes_to_canonical(cb):
    ent = {"type": "person", "name": "Ambiguous One"}
    cb.curator.apply_candidate(
        _claim(section="people", type="role", value="mentor", entity=ent,
               confidence="inferred"),
        source_type="gmail")
    pend = cb.pending()
    assert pend
    res = cb.approve(pend[0]["id"])
    assert res["outcome"] in ("added", "superseded")
    assert not cb.pending()  # queue drained


# ── freshness ───────────────────────────────────────────────────────────────
def test_freshness_only_ages_time_sensitive():
    stale_role = {"type": "role", "state": "current",
                  "last_confirmed_at": "2020-01-01T00:00:00+00:00"}
    assert freshness.compute(stale_role) == "stale"
    old_pref = {"type": "preference", "state": "current",
                "last_confirmed_at": "2020-01-01T00:00:00+00:00"}
    assert freshness.compute(old_pref) == "fresh"  # non-time-sensitive never ages


# ── recall ordering ─────────────────────────────────────────────────────────
def test_recall_block_leads_and_cites(cb):
    r = cb.curator.apply_candidate(_claim(value="prefers local-first tools"),
                                   source_type="chat")
    block = cb.recall_block("what tools do I prefer")
    assert "CANONICAL FACTS" in block["block"]
    assert r["claim_id"] in block["claim_ids"]

def test_recall_marks_stale(cb):
    cb.curator.apply_candidate(_claim(type="project_status", value="building lodestone",
                                      ts="2020-01-01"),
                               source_type="chat", source_timestamp="2020-01-01")
    cb.maintain()
    block = cb.recall_block("what am I building")
    assert "STALE" in block["block"] or "aging" in block["block"]


# ── evaluation harness ──────────────────────────────────────────────────────
def test_eval_harness_measures_recall(cb):
    r = cb.curator.apply_candidate(_claim(value="prefers local-first tools"),
                                   source_type="chat")
    cb.add_eval_case(query="what do I prefer", expected_claim_ids=[r["claim_id"]])
    report = cb.evaluate(k=5)
    assert report["canonical_recall_at_k"] == 1.0
    assert report["source_citation_coverage"] == 1.0
    assert report["wrong_current_fact_count"] == 0


# ── structural gmail ranking ────────────────────────────────────────────────
def test_thread_ranking_is_structural(cb):
    msgs = [
        {"id": "promo", "labels": ["CATEGORY_PROMOTIONS"], "sender": "deals@shop.com"},
        {"id": "convo", "from_me": True, "is_reply": True, "thread_size": 4,
         "sender": "real.person@gmail.com", "labels": ["IMPORTANT"]},
    ]
    ranked = cb.rank_threads(msgs)
    assert ranked[0]["id"] == "convo"
    assert ranked[-1]["id"] == "promo"


# ── export ──────────────────────────────────────────────────────────────────
def test_export_generates_markdown(cb, tmp_path):
    cb.curator.apply_candidate(_claim(value="prefers local-first tools"),
                               source_type="chat")
    out = cb.export(out_dir=tmp_path / "export")
    assert any(f.endswith("about-you.md") for f in out["files"])
    assert (tmp_path / "export" / "brain.json").exists()


# ── event immutability / timeline ───────────────────────────────────────────
def test_event_dedup(cb):
    ev = {"kind": "event", "event_type": "milestone", "occurred_at": "2026-09-06",
          "summary": "Shipped canonical brain", "evidence_excerpt": "x"}
    r1 = cb.curator.apply_candidate(ev, source_type="chat")
    r2 = cb.curator.apply_candidate(ev, source_type="chat")
    assert r1["outcome"] == "event_added"
    assert r2["outcome"] == "duplicate_event"
