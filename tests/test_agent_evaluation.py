"""The capability claim, measured.

"The agents are better now" is the kind of claim that rots. `agents/evaluation.py`
runs the real loop against a scripted model — no network, no keys, no spend —
and returns a number that can be compared between commits.

The most important test in this file is the last one: a scorecard that cannot
fail is decoration, so it is run again with a capability deliberately broken.
"""
import pytest

from chitragupta.agents import evaluation

#: Every check is binary — the capability works or it does not — so the floor is
#: all of them. A softer floor was tried first and rejected on evidence: with 15
#: checks each is worth 0.67, so switching off the repeat guard scored 9.3 and a
#: 9.0 gate let a real regression through.
MINIMUM_SCORE = 10.0


@pytest.fixture(scope="module")
def card():
    return evaluation.run()


def test_the_agents_meet_the_capability_floor(card):
    assert card.score >= MINIMUM_SCORE, (
        f"agent capability fell to {card.score}/10:\n"
        + "\n".join(f"  - {c.title}" for c in card.failures()))


def test_every_check_ran(card):
    assert card.total >= 15, "the scorecard lost checks"
    assert card.passed == card.total or card.failures()


@pytest.mark.parametrize("key", [
    "depth", "effort", "no_repeat", "stall", "budget_answer", "parallel",
    "planning", "delegation", "delegation_guard", "grounding", "streaming",
    "unattended_outbound", "no_escalation", "reads_stay_free", "tool_validation",
    "connector_tools", "connector_writes_withheld",
])
def test_the_named_capabilities_are_all_covered(card, key):
    """Named individually so deleting one from the scorecard fails here rather
    than quietly lowering the total."""
    assert any(c.key == key for c in card.checks), f"{key} is no longer checked"


def test_the_scorecard_is_serialisable_for_the_ui(card):
    body = card.as_dict()
    assert body["score"] == card.score
    assert len(body["checks"]) == card.total
    assert all({"key", "title", "passed"} <= set(c) for c in body["checks"])


def test_the_scorecard_notices_when_a_capability_breaks(monkeypatch):
    """A scorecard that always passes measures nothing.

    The repeat memo is switched off — the guard that stops a deep loop
    re-issuing the same call forever — and the score must drop.
    """
    from chitragupta.agents import loop

    class _Forgetful(loop.ToolRunner):
        def run(self, calls):
            self._memo.clear()           # never remember, so never dedupe
            return super().run(calls)

    monkeypatch.setattr("chitragupta.agents.runtime.ToolRunner", _Forgetful)
    broken = evaluation.run(include_slow=False)

    assert broken.score < MINIMUM_SCORE, (
        "the scorecard passed with the repeat guard removed — it is not "
        "measuring anything")
    # Named, not merely counted: a lower total could come from anywhere, and
    # the point is that *this* capability is the one the scorecard noticed.
    assert any(c.key == "no_repeat" for c in broken.failures()), (
        f"the wrong check failed: {[c.key for c in broken.failures()]}")
