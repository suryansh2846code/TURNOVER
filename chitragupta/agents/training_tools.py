"""Reading the training log.

Writing is not here. A session is proposed as a `log_workout` action and lands
on a card the user can correct in place, because the gap between what they said
and what was understood is wide: "5x5 squats, last one a grind, then some
bench" is four numbers, a judgement and two exercise names, and a session stored
wrong is a wrong trend for months, noticed weeks later.

Reading is three questions, and they are different questions:

* `list_exercises` — what has a history at all, and under which spelling. The
  agent checks this before inventing a new name, or "Squat" and "back squat"
  become two lifts with two half-histories.
* `lift_progress` — what has happened to one lift: volume, the best set, and
  what it estimates a single at. The arithmetic is done in `training.py`, not
  by a model adding up forty sets.
* `training_load` — total tonnage per week, for "am I doing more or less than
  I was".

Storage and the two derived numbers: `chitragupta/training.py`.
"""
from __future__ import annotations

from ..log import get_logger
from .results import ToolResult

log = get_logger(__name__)

#: Sessions listed under a progress summary. The summary is the answer; these
#: are so the agent can quote a specific day.
RECENT_SHOWN = 10

NOTHING_LOGGED = (
    "No training logged yet. When the user describes a session, propose a "
    "log_workout action — they will see what you understood and can correct it "
    "before it is saved. Do not invent a history they have not given you.")


def list_exercises() -> ToolResult:
    """Every exercise with a history, most recently trained first."""
    from ..training import exercises

    rows = exercises()
    if not rows:
        return ToolResult(NOTHING_LOGGED)

    lines = ["Exercises with a logged history — reuse these exact names:"]
    for row in rows:
        lines.append(f"- {row['exercise']} — {row['entries']} entr"
                     f"{'y' if row['entries'] == 1 else 'ies'}, last "
                     f"{row['last'][:10]}, heaviest {row['heaviest']:g} kg")
    lines.append("\nIf the user means one of these, use its exact spelling. A "
                 "new spelling starts a separate history.")
    return ToolResult("\n".join(lines))


def lift_progress(exercise: str, days: int = 180) -> ToolResult:
    """What has happened to one lift: volume, best set, estimated max."""
    from ..training import history, progress

    name = str(exercise or "").strip()
    if not name:
        return ToolResult.failed("Which exercise? `list_exercises` has the names.")

    summary = progress(name, days=max(1, min(3650, int(days or 180))))
    if summary.get("n", 0) == 0:
        return ToolResult(
            f"{summary['detail']} Say so rather than estimating — and check "
            "`list_exercises` in case they call it something else.")

    best = summary["best_set"]
    heaviest = summary["heaviest"]
    lines = [
        f"{summary['exercise']} — {summary['n']} entr"
        f"{'y' if summary['n'] == 1 else 'ies'} across {summary['sessions']} "
        f"session(s), {summary['first']} to {summary['last']}.",
        f"  volume: {summary['total_volume']:,.0f} kg total, "
        f"{summary['volume_per_session']:,.0f} kg per session",
        f"  earlier sessions averaged {summary['volume_early']:,.0f} kg, "
        f"recent ones {summary['volume_recent']:,.0f} kg",
        f"  heaviest: {heaviest['weight']:g} kg × {heaviest['reps']} "
        f"on {heaviest['at']}",
        f"  best set: {best['weight']:g} kg × {best['reps']} on {best['at']} "
        f"— estimates a single at {best['estimated_max']:g} kg",
        f"  (that estimate is {summary['formula']}, not a lift they have done)",
    ]

    rows = history(name, days=days, limit=2000)[-RECENT_SHOWN:]
    lines.append(f"\nMost recent {len(rows)} entr"
                 f"{'y' if len(rows) == 1 else 'ies'}:")
    for row in rows:
        effort = f", RPE {row['rpe']:g}" if row["rpe"] else ""
        note = f"  — {row['note']}" if row["note"] else ""
        lines.append(f"  {row['at'][:10]}  {row['sets']}×{row['reps']} @ "
                     f"{row['weight']:g} kg{effort}{note}")
    return ToolResult("\n".join(lines))


def training_load(weeks: int = 12) -> ToolResult:
    """Total tonnage per week — whether they are training more or less."""
    from ..training import weekly_volume

    span = max(1, min(104, int(weeks or 12)))
    rows = weekly_volume(days=span * 7)
    if not rows:
        return ToolResult(NOTHING_LOGGED)

    lines = [f"Training volume by week, last {len(rows)} week(s) with anything "
             "logged:"]
    lines += [f"  week of {r['week_of']}  {r['volume']:,.0f} kg" for r in rows]
    if len(rows) >= 2:
        first, last = rows[0]["volume"], rows[-1]["volume"]
        # Two weeks is not a trend, and saying so is the same rule the
        # measurement store applies to body weight.
        if len(rows) < 4:
            lines.append("\nToo few weeks to call this a trend — say what the "
                         "numbers are, not what they mean.")
        elif first:
            change = (last - first) / first * 100
            lines.append(f"\nMost recent week is {change:+.0f}% against the "
                         f"first week shown. Weeks missing from this list are "
                         "weeks with nothing logged, which may mean rest or may "
                         "mean they stopped logging — ask rather than assume.")
    return ToolResult("\n".join(lines))
