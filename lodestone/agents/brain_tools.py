"""Reaching the brain properly, instead of searching across it and hoping.

The knowledge graph and the curated canonical layer are what the product is
built on, and until now an agent could address almost none of them. `Brain` and
`Canonical` expose about a dozen query methods between them; exactly one —
`top_entities`, as `list_entities` — was wired to a tool. Everything else was
reachable only through one blunt semantic search.

So "who is Divyansh and what am I working on with him" was a vector search that
hoped, when `match_entities` → `facts_for` → `get_related` would have answered
it exactly. And an agent could *add* a fact about the user but never fix a wrong
one: the user says "no, I left that job in March" and the agent had no hands,
so the stale fact stayed and kept being recalled.

Two deliberate boundaries:

* **Correcting is superseding, never editing.** Claims are append-only — that
  invariant belongs to `brain/`, and the tool here is shaped so it cannot be
  broken from this side.
* **Forgetting is not in the base tool set.** These agents read email, issues and
  messages written by other people, and "forget everything about X" is a
  sentence an injection would write. An agent gets `forget_fact` only when the
  user puts it in that agent's tool list, and it is a soft retraction that keeps
  provenance, so a mistake is recoverable.
"""
from __future__ import annotations

from ..brain import get_brain
from ..log import suppressed
from .results import ToolResult

#: Keeps a single answer readable and cheap. These are read back by a model,
#: so a person's whole history would spend the turn's context on one call.
MAX_FACTS = 10
MAX_RELATED = 8
MAX_CLAIMS = 12
MAX_TIMELINE = 25

#: How close a recall hit must be before a tool will act ON that memory rather
#: than merely read it. Recall always returns a nearest neighbour, so without a
#: floor `correct_fact` would supersede — and `forget_fact` would retract — an
#: entirely unrelated memory whenever the thing being corrected was not in the
#: brain at all. Measured on this store: a true match scores ~1.6, while
#: unrelated text scores 0.79–0.95, so the gap is wide and 1.2 sits in it.
#: Erring high is the safe direction: the cost of being too strict is recording
#: a new fact instead of replacing one, and the cost of being too loose is
#: quietly destroying something the user said.
MIN_MATCH_SCORE = 1.2


def _confident_hit(brain, text: str) -> dict | None:
    """The memory `text` refers to, or None if nothing is close enough."""
    hits = brain.recall(text, limit=1)["memory_hits"]
    if not hits:
        return None
    return hits[0] if float(hits[0].get("score") or 0) >= MIN_MATCH_SCORE else None


def _canonical():
    """The curated layer, or None on a checkout that has not built it."""
    with suppressed("from ..brain.canonical import get_canonical …"):
        from ..brain.canonical import get_canonical
        return get_canonical()
    return None


def _claim_line(claim: dict) -> str:
    text = (claim.get("text") or claim.get("value") or "").strip()
    fresh = (claim.get("freshness") or {}) if isinstance(claim.get("freshness"), dict) else {}
    stale = fresh.get("stale") or fresh.get("is_stale")
    return f"- {text}" + ("  (may be out of date)" if stale else "")


# ── who ──────────────────────────────────────────────────────────────────
def who_is(name: str) -> ToolResult:
    """Everything the brain holds about one person, project or organisation."""
    query = (name or "").strip()
    if not query:
        return ToolResult.failed("Give a name to look up.")

    brain = get_brain()
    matches = brain.graph.match_entities(query, limit=3)
    if not matches:
        # Not a failure: the honest answer is that this person is not in the
        # brain yet, and saying so is more useful than a retry.
        return ToolResult(
            f"Nothing in the knowledge graph matches '{query}'. "
            "They may not have been mentioned in anything synced yet.")

    top = matches[0]
    lines = [f"{top.get('name')} — {top.get('type') or 'unknown type'}"
             f" (mentioned {top.get('mentions', 0)}×)"]
    if top.get("summary"):
        lines.append(str(top["summary"]).strip())

    facts = brain.graph.facts_for(top["id"], limit=MAX_FACTS)
    if facts:
        lines.append("\nWhat the brain knows:")
        lines += [f"- {f}" for f in facts]

    related = brain.get_related(top["id"], limit=MAX_RELATED)
    if related:
        lines.append("\nConnected to:")
        for r in related:
            how = r.get("predicate") or r.get("fact") or "related"
            lines.append(f"- {r.get('target_name')} ({r.get('target_type')}) — {how}")

    canon = _canonical()
    if canon is not None:
        with suppressed("reading curated claims for an entity"):
            for person in canon.people() + canon.work():
                if str(person.get("name", "")).lower() != str(top.get("name", "")).lower():
                    continue
                claims = person.get("claims") or []
                if claims:
                    lines.append("\nCurated facts (evidence-backed):")
                    lines += [_claim_line(c) for c in claims[:MAX_CLAIMS]]
                break

    if len(matches) > 1:
        others = ", ".join(str(m.get("name")) for m in matches[1:])
        lines.append(f"\n(Also matched: {others}. Ask again by full name if it "
                     "was one of those.)")
    return ToolResult("\n".join(lines))


# ── the curated view of the user ─────────────────────────────────────────
def whats_true_about_me(area: str = "all") -> ToolResult:
    """The curated, evidence-backed model of the user — not a search over it."""
    canon = _canonical()
    if canon is None:
        return ToolResult.failed("The curated layer is not available on this install.")

    wanted = (area or "all").strip().lower()
    blocks: list[str] = []

    if wanted in ("all", "about_you", "me", "personal"):
        claims = canon.about_you()
        if claims:
            blocks.append("ABOUT THE USER:\n"
                          + "\n".join(_claim_line(c) for c in claims[:MAX_CLAIMS]))
    if wanted in ("all", "people"):
        people = canon.people()
        if people:
            blocks.append("PEOPLE:\n" + "\n".join(
                f"- {p.get('name')}" + (f" — {len(p.get('claims') or [])} known facts"
                                        if p.get("claims") else "")
                for p in people[:MAX_CLAIMS]))
    if wanted in ("all", "work", "projects"):
        work = canon.work()
        if work:
            blocks.append("WORK — projects and organisations:\n" + "\n".join(
                f"- {w.get('name')} ({w.get('type')})" for w in work[:MAX_CLAIMS]))

    if not blocks:
        return ToolResult(
            "The curated layer has nothing recorded for that yet. It fills in as "
            "sources are synced and conversations happen.")
    return ToolResult("\n\n".join(blocks))


def timeline(limit: int = MAX_TIMELINE) -> ToolResult:
    """What happened, in order — rather than a semantic search over episodic noise."""
    canon = _canonical()
    if canon is None:
        return ToolResult.failed("The curated layer is not available on this install.")
    try:
        bound = max(1, min(int(limit or MAX_TIMELINE), 100))
    except (TypeError, ValueError):
        bound = MAX_TIMELINE
    events = canon.timeline(limit=bound)
    if not events:
        return ToolResult("The timeline is empty — nothing dated has been curated yet.")
    lines = []
    for e in events[:bound]:
        when = (e.get("at") or e.get("date") or e.get("source_timestamp") or "")[:10]
        what = (e.get("text") or e.get("title") or e.get("summary") or "").strip()
        if what:
            lines.append(f"- {when or 'undated'}: {what}")
    return ToolResult("\n".join(lines) if lines
                      else "Nothing dated has been curated yet.")


# ── provenance ───────────────────────────────────────────────────────────
def why_do_you_think_that(claim: str) -> ToolResult:
    """Where a fact came from and how confident the brain is in it."""
    text = (claim or "").strip()
    if not text:
        return ToolResult.failed("Say which claim to explain.")

    brain = get_brain()
    hit = _confident_hit(brain, text)
    if hit is None:
        return ToolResult(f"Nothing in the brain matches '{text}', so there is "
                          "nothing to explain — it did not come from a memory.")

    detail = brain.explain_memory(hit["id"], text)
    lines = [f"That comes from a memory recorded on "
             f"{str(hit.get('created_at') or '')[:10] or 'an unknown date'}"
             f" from {hit.get('source') or 'an unknown source'}:",
             f'  "{(hit.get("text") or "")[:400]}"']
    if detail.get("activation") is not None:
        lines.append(f"Confidence {hit.get('confidence', '?')}, "
                     f"reinforced {detail.get('reinforcement_count', 0)}×.")
    if hit.get("status") and hit["status"] != "active":
        lines.append(f"Note: this memory is marked {hit['status']}.")
    return ToolResult("\n".join(lines))


def check_for_contradictions() -> ToolResult:
    """Facts that disagree with each other, so the user can settle them."""
    conflicts = get_brain().detect_contradictions()
    if not conflicts:
        return ToolResult("No contradictions found in the brain.")
    lines = ["The brain holds facts that disagree:"]
    for c in conflicts[:8]:
        a = (c.get("a") or {}).get("text") or c.get("text_a") or ""
        b = (c.get("b") or {}).get("text") or c.get("text_b") or ""
        lines.append(f'- "{a[:120]}"  vs  "{b[:120]}"')
    return ToolResult("\n".join(lines))


# ── changing what the brain believes ─────────────────────────────────────
def correct_fact(old: str, new: str) -> ToolResult:
    """Replace something the brain believes with what is actually true.

    Supersedes rather than edits: claims are append-only, so the old fact stays
    as history and stops being recalled. That invariant lives in `brain/`; this
    is shaped so it cannot be broken from here.
    """
    stale, fresh = (old or "").strip(), (new or "").strip()
    if not stale or not fresh:
        return ToolResult.failed(
            "Say both what is wrong and what is actually true.")

    brain = get_brain()
    hit = _confident_hit(brain, stale)
    if hit is None:
        # Nothing close enough to be sure of. Record the truth rather than
        # replace whatever happened to be nearest — see MIN_MATCH_SCORE.
        brain.ingest(fresh, source="agent", kind="fact", title="corrected")
        return ToolResult(
            f"The brain had nothing matching '{stale[:60]}', so I recorded the "
            "correct version as a new fact instead.")

    out = brain.supersede(hit["id"], fresh)
    if not out.get("ok"):
        return ToolResult.failed(
            f"Could not replace that fact: {out.get('error') or 'unknown reason'}")
    return ToolResult(
        f'Updated. The brain now holds "{fresh[:120]}" and no longer recalls the '
        "old version, which is kept as history.")


def forget_fact(fact: str) -> ToolResult:
    """Retract something, keeping provenance so it can be recovered.

    Not in the base tool set — see the module docstring. An agent reading other
    people's text should not have this unless the user chose to give it.
    """
    text = (fact or "").strip()
    if not text:
        return ToolResult.failed("Say what to forget.")

    brain = get_brain()
    hit = _confident_hit(brain, text)
    if hit is None:
        # Refusing beats retracting the nearest thing. Destroying the wrong
        # memory is the one mistake here the user cannot see us make.
        return ToolResult(
            f"Nothing in the brain clearly matches '{text[:60]}', so I have not "
            "retracted anything. Say it closer to how it is recorded.")
    if not brain.forget(hit["id"], soft=True):
        return ToolResult.failed("Could not retract that memory.")
    return ToolResult(
        f'Retracted: "{(hit.get("text") or "")[:120]}". It is no longer '
        "recalled, and the record of it having been there is kept.")
