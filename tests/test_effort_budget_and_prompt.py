"""Two ceilings that were missing, and a prompt that told every agent everything.

Effort capped rounds and never cost, and nothing bounded a delegation chain in
aggregate — docs/AGENTS.md has listed that as missing since delegation landed.
Separately, one ~60-line prompt went to every agent: Research, which has no way
to send anything, was handed the full send_email protocol on every round.
"""
from __future__ import annotations

from agent_harness import ScriptedProvider

from chitragupta.agents import delegation, prompt, runtime
from chitragupta.agents.effort import HIGH, LOW, MEDIUM
from chitragupta.agents.presets import PRESETS, get_agent


# ── the token ceiling ────────────────────────────────────────────────────
def test_every_level_has_a_spend_ceiling():
    for level in (LOW, MEDIUM, HIGH):
        assert level.max_tokens_per_turn > 0, f"{level.name} is unbounded"
    assert LOW.max_tokens_per_turn < MEDIUM.max_tokens_per_turn < HIGH.max_tokens_per_turn


def test_a_sub_agent_shares_the_ledger_rather_than_getting_its_own():
    """Otherwise three agents at High spend three budgets, not one."""
    parent = delegation.enter("inbox", HIGH)
    try:
        ledger = delegation.current_chain().spend
        assert ledger is not None and ledger.limit == HIGH.max_tokens_per_turn
        ledger.add(1000)

        child = delegation.enter("research", HIGH.child())
        try:
            inherited = delegation.current_chain().spend
            assert inherited is ledger, "the sub-agent opened its own budget"
            assert inherited.used == 1000
        finally:
            delegation.leave(child)
    finally:
        delegation.leave(parent)


def test_the_child_budget_does_not_halve_the_ledger():
    """Halving would bound each hop twice and the whole chain not at all."""
    assert HIGH.child().max_tokens_per_turn == HIGH.max_tokens_per_turn
    assert HIGH.child().max_steps < HIGH.max_steps        # rounds still shrink


def test_a_spent_turn_cannot_pass_the_question_on():
    token = delegation.enter("inbox", HIGH)
    try:
        delegation.current_chain().spend.add(HIGH.max_tokens_per_turn + 1)
        why_not = delegation.refusal("research")
        assert why_not is not None
        assert "budget" in why_not
    finally:
        delegation.leave(token)


def test_a_turn_that_spends_its_budget_still_answers(monkeypatch):
    """Running out of money ends the looking, not the turn."""
    class _Expensive(ScriptedProvider):
        def chat(self, messages, *, tools=None, temperature=0.7, max_tokens=1500):
            result = super().chat(messages, tools=tools, temperature=temperature,
                                  max_tokens=max_tokens)
            result.input_tokens, result.output_tokens = 500_000, 1000
            return result

    provider = _Expensive(
        script=[[("list_entities", {"limit": i})] for i in range(24)],
        final_answer="here is what I found before the budget ran out")
    monkeypatch.setattr(runtime, "get_provider", lambda p, m: provider)
    monkeypatch.setattr(runtime, "resolve_usable_model", lambda p, m: (m or "x", None))

    result = runtime.run_turn("research", "dig deep", effort="low")

    assert result.reply, "a spent turn produced nothing at all"
    assert result.steps_used < 24, "the budget did not curtail the looking"


# ── the prompt ───────────────────────────────────────────────────────────
def test_an_agent_with_no_actions_is_not_taught_how_to_send_email():
    research = get_agent("research")
    assert research.actions == []
    text = research.system_message()
    assert "send_email" not in text, "Research carries the email protocol"
    assert "create_routine" not in text
    assert "at=" not in text, "and the scheduling rules that depend on it"


def test_an_agent_that_can_send_still_gets_the_whole_protocol():
    inbox = get_agent("inbox")
    text = inbox.system_message()
    for needed in ("send_email", "create_event", "set_reminder", "create_routine",
                   "Confirm button"):
        assert needed in text, f"Inbox lost {needed}"


def test_dropping_the_dead_blocks_is_a_real_saving():
    small = len(get_agent("research").system_message())
    full = len(get_agent("inbox").system_message())
    assert small < full * 0.75, (
        f"expected a meaningful cut; got {small} vs {full} chars")


def test_every_agent_still_gets_the_rules_that_always_apply():
    for agent in PRESETS.values():
        text = agent.system_message()
        assert "ALREADY been ingested" in text, f"{agent.id} lost the brain rule"
        assert "NEVER claim you did something" in text
        assert agent.name in text and agent.role in text


def test_a_typo_in_an_actions_list_produces_nothing_not_a_crash():
    text = prompt.build(name="X", role="y", system_prompt="z",
                        actions=["send_emial", "nonsense"])
    assert "Confirm button" not in text


def test_an_agent_the_user_built_keeps_the_proposals_it_had():
    """Narrowing one silently would take away something they already had."""
    from chitragupta.agents.custom import get_custom_store

    store = get_custom_store()
    made = store.create("Budget Helper", role="money", system_prompt="help")
    try:
        assert set(made.actions) == set(prompt.KNOWN_ACTIONS)
        assert "send_email" in made.system_message()
    finally:
        store.delete(made.id)
