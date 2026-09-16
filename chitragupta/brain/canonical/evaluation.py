"""Evaluation harness — build this BEFORE trusting automatic curation.

A Brain that retrieves ten plausible facts but gets the current one wrong is
not trustworthy. These metrics make that measurable.
"""
from __future__ import annotations

from . import recall
from .store import CanonicalStore


def run(store: CanonicalStore, *, k: int = 5) -> dict:
    cases = store.eval_cases()
    if not cases:
        return {"cases": 0, "note": "no evaluation_cases defined"}

    claim_hits = ent_hits = 0
    claim_total = ent_total = 0
    wrong_current = 0          # a historical/superseded fact returned as current
    stale_disclosed = 0        # stale facts that were surfaced WITH a stale marker
    stale_total = 0
    src_cov_hits = src_cov_total = 0

    for case in cases:
        res = recall.build_block(store, case["query"], max_claims=k)
        got_claims = set(res["claim_ids"])
        got_ents = set(res["entity_ids"])

        exp_claims = set(case["expected_claim_ids"])
        exp_ents = set(case["expected_entity_ids"])
        if exp_claims:
            claim_total += 1
            if exp_claims & got_claims:
                claim_hits += 1
        if exp_ents:
            ent_total += 1
            if exp_ents & got_ents:
                ent_hits += 1

        # correctness: none of the returned claims may be non-current
        for cid in got_claims:
            c = store.get_claim(cid)
            if c and c["state"] not in ("current", "open"):
                wrong_current += 1
            if c:
                from . import freshness
                if freshness.compute(c) == "stale":
                    stale_total += 1
                    if "STALE" in res["block"]:
                        stale_disclosed += 1
                # source citation coverage
                src_cov_total += 1
                if store.evidence_for_claim(cid):
                    src_cov_hits += 1

    def ratio(a, b):
        return round(a / b, 3) if b else None

    return {
        "cases": len(cases),
        "k": k,
        "canonical_recall_at_k": ratio(claim_hits, claim_total),
        "entity_recall_at_k": ratio(ent_hits, ent_total),
        "wrong_current_fact_count": wrong_current,
        "stale_disclosure_rate": ratio(stale_disclosed, stale_total),
        "source_citation_coverage": ratio(src_cov_hits, src_cov_total),
    }
