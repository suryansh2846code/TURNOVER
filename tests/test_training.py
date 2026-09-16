"""Sets, reps and load.

`metrics.py` holds one number at one moment, which is right for a body weight
and wrong for a session: "five sets of five at 100, last one a grind" is four
numbers and a judgement, and flattening it to one figure throws away the part
that decides what to do next week.

Two things are pinned hardest. That a typo is refused rather than stored — a
wrong entry is a wrong trend for months, noticed weeks later. And that the two
derived numbers are arithmetic, not estimation: volume is exact, and the
estimated max says out loud that it is an estimate from a named formula.

Storage decisions: lodestone/training.py
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lodestone import actions, training
from lodestone.agents import training_tools
from lodestone.agents.approvals import describe


@pytest.fixture(autouse=True)
def clean():
    yield
    for row in training.exercises():
        for entry in training.history(row["exercise"], days=36500, limit=5000):
            training.forget_session(entry["session_id"])


def _log(exercise, sets, reps, weight, *, days_ago=0, rpe=None):
    at = (datetime.now(UTC) - timedelta(days=days_ago)).replace(
        hour=12, minute=0, second=0, microsecond=0).isoformat()
    blocks, problem = training.parse_blocks(
        [{"exercise": exercise, "sets": sets, "reps": reps, "weight": weight,
          "rpe": rpe}])
    assert not problem, problem
    return training.log_session(blocks, at=at)


# ── a block is how people write it down ──────────────────────────────────
def test_a_session_is_stored_as_written():
    out = _log("Squat", 5, 5, 100, rpe=8)
    assert out["ok"]
    assert out["volume"] == 2500
    assert "Squat 5×5 @ 100 kg, RPE 8" in out["detail"]


def test_bodyweight_work_is_a_real_entry():
    """Zero load is not missing data."""
    out = _log("Pull-up", 4, 8, 0)
    assert out["ok"]
    assert "bodyweight" in out["detail"]


def test_different_weights_are_different_blocks():
    """100x5 then 105x3 is two entries, not one averaged one."""
    blocks, problem = training.parse_blocks([
        {"exercise": "Deadlift", "sets": 1, "reps": 5, "weight": 100},
        {"exercise": "Deadlift", "sets": 1, "reps": 3, "weight": 105},
    ])
    assert not problem
    out = training.log_session(blocks)
    assert out["blocks"] == 2
    assert out["volume"] == 100 * 5 + 105 * 3


# ── a typo is refused, not stored ────────────────────────────────────────
@pytest.mark.parametrize("entry, because", [
    ({"exercise": "Squat", "sets": 5, "reps": 5, "weight": 9000}, "absurd weight"),
    ({"exercise": "Squat", "sets": 5, "reps": 5, "weight": -20}, "negative weight"),
    ({"exercise": "Squat", "sets": 0, "reps": 5, "weight": 100}, "no sets"),
    ({"exercise": "", "sets": 5, "reps": 5, "weight": 100}, "no name"),
    ({"exercise": "Squat", "sets": "five", "reps": 5, "weight": 100}, "not a number"),
])
def test_a_wrong_entry_is_refused_whole(entry, because):
    blocks, problem = training.parse_blocks([entry])
    assert not blocks and problem, because


def test_one_bad_entry_refuses_the_whole_session():
    """The user confirmed a card that listed every block."""
    blocks, problem = training.parse_blocks([
        {"exercise": "Squat", "sets": 5, "reps": 5, "weight": 100},
        {"exercise": "Bench", "sets": 3, "reps": 8, "weight": 9000},
    ])
    assert not blocks
    assert "9000" in problem and "typo" in problem


def test_the_refusal_says_how_to_mean_bodyweight():
    _blocks, problem = training.parse_blocks(
        [{"exercise": "Dip", "sets": 3, "reps": 8, "weight": -1}])
    assert "0 for bodyweight" in problem


# ── the two derived numbers ──────────────────────────────────────────────
def test_volume_is_exact_arithmetic():
    _log("Squat", 5, 5, 100)
    _log("Squat", 3, 8, 80, days_ago=3)
    summary = training.progress("Squat")
    assert summary["total_volume"] == 5 * 5 * 100 + 3 * 8 * 80


def test_the_estimated_max_compares_sets_that_are_not_comparable():
    """5 at 100 against 3 at 110 is the whole question."""
    _log("Deadlift", 1, 5, 100)
    _log("Deadlift", 1, 3, 110, days_ago=7)
    best = training.progress("Deadlift")["best_set"]
    assert best["weight"] == 110, "it picked the heavier volume, not the better set"
    assert 119 < best["estimated_max"] < 122


def test_the_estimate_names_its_formula():
    """Other formulas disagree; presenting it as a measurement would be wrong."""
    _log("Squat", 5, 5, 100)
    assert "Epley" in training.progress("Squat")["formula"]


# ── one exercise, one history ────────────────────────────────────────────
def test_spelling_does_not_split_a_history():
    """"Squat" and "squat" are the same lift."""
    _log("Squat", 5, 5, 100)
    _log("squat", 5, 5, 105, days_ago=7)
    assert training.progress("SQUAT")["n"] == 2
    assert len(training.exercises()) == 1


def test_the_user_s_own_spelling_is_what_is_shown():
    _log("Barbell Row", 3, 10, 60)
    assert training.exercises()[0]["exercise"] == "Barbell Row"


# ── correcting a session ─────────────────────────────────────────────────
def test_a_session_can_be_removed():
    out = _log("Squat", 5, 5, 100)
    assert training.forget_session(out["session_id"]) == 1
    assert training.progress("Squat")["n"] == 0


def test_the_last_session_can_be_pointed_at():
    """So "undo that" has something to mean."""
    _log("Squat", 5, 5, 100, days_ago=3)
    recent = _log("Bench", 3, 8, 60)
    assert training.last_session()["session_id"] == recent["session_id"]


# ── the card ─────────────────────────────────────────────────────────────
def test_the_card_says_what_will_be_logged():
    line = describe("log_workout", {"blocks": [
        {"exercise": "Squat", "sets": 5, "reps": 5, "weight": 100, "rpe": 8},
        {"exercise": "Bench press", "sets": 3, "reps": 8, "weight": 60}]})
    assert "Squat 5×5 @ 100 kg" in line
    assert "RPE 8" in line
    assert "3,940 kg total" in line


def test_the_card_shows_no_internals():
    line = describe("log_workout", {"blocks": [
        {"exercise": "Squat", "sets": 5, "reps": 5, "weight": 100}]})
    assert "log_workout" not in line and "session_id" not in line


def test_the_action_runs_what_was_confirmed():
    out = actions.run_now("log_workout", {"blocks": [
        {"exercise": "Squat", "sets": 5, "reps": 5, "weight": 105}]})
    assert out["ok"]
    assert training.progress("Squat")["heaviest"]["weight"] == 105


def test_the_action_refuses_a_typo_rather_than_storing_it():
    out = actions.run_now("log_workout", {"blocks": [
        {"exercise": "Squat", "sets": 5, "reps": 5, "weight": 9000}]})
    assert not out["ok"]
    assert training.progress("Squat")["n"] == 0


# ── the reading tools ────────────────────────────────────────────────────
def test_with_nothing_logged_it_is_told_not_to_invent_a_history():
    out = training_tools.list_exercises()
    assert "Do not invent a history" in out


def test_it_is_told_to_reuse_the_existing_spelling():
    _log("Barbell Row", 3, 10, 60)
    out = training_tools.list_exercises()
    assert "Barbell Row" in out
    assert "separate history" in out


def test_progress_hands_back_the_arithmetic():
    _log("Squat", 5, 5, 100, days_ago=14)
    _log("Squat", 5, 5, 105)
    out = training_tools.lift_progress("Squat")
    assert out.ok
    assert "volume" in out and "best set" in out
    assert "Epley" in out, "the estimate does not say it is an estimate"


def test_a_lift_with_no_history_says_so():
    out = training_tools.lift_progress("Snatch")
    assert "No Snatch logged" in out
    assert "list_exercises" in out, "it does not suggest checking the spelling"


def test_two_weeks_is_not_called_a_trend():
    _log("Squat", 5, 5, 100, days_ago=8)
    _log("Squat", 5, 5, 105, days_ago=1)
    out = training_tools.training_load(weeks=12)
    assert "Too few weeks" in out


def test_a_missing_week_is_not_read_as_a_rest_week():
    for week in range(6):
        _log("Squat", 5, 5, 100, days_ago=week * 7)
    out = training_tools.training_load(weeks=12)
    assert "may mean rest or may mean they stopped logging" in out
