"""Measurements an agent can record, read and correct.

The Health agent's own brief said "review honestly rather than encouragingly"
and it had nothing to review. Weight, sleep and training went into the brain as
prose, and the only way back was recall — so every answer about progress was a
model reading a handful of retrieved sentences and estimating. The repo already
had the rule written down for the Inbox agent: a number you estimated is a
number you made up.

Four tools, and the fourth is the one that is easy to leave out:

* `whats_tracked` — what data actually exists. Without it the agent guesses,
  and guesses in both directions: claiming to know a trend it has three
  readings for, or saying it has no weight data when there are two years of it.
* `measurement_history` — the arithmetic already done. A model asked to average
  ninety numbers in its head will produce a number; it will not produce the
  right one.
* `log_measurement` — recording one reading.
* `forget_measurement` — removing a wrong one. A mistyped `780` otherwise sits
  in the series forever, poisoning every average, visible to the user and
  fixable by nobody.

Storage and why it is not the brain: `lodestone/metrics.py`.
"""
from __future__ import annotations

from ..log import get_logger
from ..metrics import METRICS, known
from .results import ToolResult

log = get_logger(__name__)

#: Readings shown after the summary. The summary is the answer; the readings
#: are so the agent can see the shape and quote a specific day.
RECENT_SHOWN = 14


def _numbers(summary: dict) -> list[str]:
    lines = [
        f"{summary['n']} reading(s) of {summary['metric']} "
        f"({summary.get('about') or summary['metric']}), in {summary['unit']}.",
        f"  first: {summary['first']['value']:g} on {summary['first']['at'][:10]}",
        f"  last:  {summary['last']['value']:g} on {summary['last']['at'][:10]}",
        f"  range: {summary['min']:g} to {summary['max']:g}, mean {summary['mean']:g}",
        f"  raw change first→last: {summary['change']:+g} {summary['unit']}",
    ]
    if "total" in summary:
        lines.append(f"  total: {summary['total']:g} {summary['unit']}, "
                     f"averaging {summary['per_day']:g} a day")

    trend = summary.get("trend")
    if trend:
        lines += [
            "  SMOOTHED TREND (use this, not the raw change):",
            f"    {trend['from']:g} → {trend['to']:g} {summary['unit']}, "
            f"{trend['change']:+g} overall, {trend['per_week']:+g} per week",
            f"    based on {trend['basis']}",
        ]
    elif summary.get("trend_note"):
        lines.append(f"  {summary['trend_note']}")
    return lines


def whats_tracked() -> ToolResult:
    """Which measurements the user actually has data for, and how much.

    Ask this before saying anything about a trend. It is the difference between
    "you are up 2 kg over six weeks" and "I have two readings, which is not
    enough to say".
    """
    from ..metrics import tracked

    rows = tracked()
    if not rows:
        return ToolResult(
            "No measurements recorded yet. You can log one with "
            "`log_measurement`, or the user can import their Apple Health "
            "export under Connectors — on their iPhone, Health → their picture "
            "→ Export All Health Data.\n"
            f"Things that can be tracked: {', '.join(known())}.")

    lines = ["What the user has measurements for:"]
    for row in rows:
        metric = METRICS.get(row["metric"])
        unit = metric.unit if metric else ""
        lines.append(f"- {row['metric']} ({unit}) — {row['n']} reading(s), "
                     f"{row['first'][:10]} to {row['last'][:10]}")
    missing = [m for m in known() if m not in {r["metric"] for r in rows}]
    if missing:
        lines.append(f"\nNo data for: {', '.join(missing)}. "
                     "Do not guess at these; say they are not being tracked.")
    return ToolResult("\n".join(lines))


def measurement_history(metric: str, days: int = 90) -> ToolResult:
    """A measurement over time, with the arithmetic already done."""
    from ..metrics import history, resolve, summarise

    found = resolve(metric)
    if found is None:
        return ToolResult.failed(
            f"“{metric}” is not something I track. I can track: "
            f"{', '.join(known())}.")

    window = max(1, min(3650, int(days or 90)))
    summary = summarise(found.name, days=window)
    if summary.get("n", 0) == 0:
        return ToolResult(
            f"No {found.name} readings in the last {window} days. Say so — do "
            "not estimate one from anything you remember.")

    lines = _numbers(summary)
    rows = history(found.name, days=window, limit=5000)
    recent = rows[-RECENT_SHOWN:]
    lines.append(f"\nMost recent {len(recent)} reading(s):")
    lines += [f"  {r['at'][:10]}  {r['value']:g} {r['unit']}"
              f"{'  (' + r['source'] + ')' if r['source'] != 'manual' else ''}"
              for r in recent]
    if len(rows) > len(recent):
        lines.append(f"  … {len(rows) - len(recent)} earlier reading(s) not listed. "
                     "Use run_python on this if you need more than the summary.")
    return ToolResult("\n".join(lines))


def log_measurement(metric: str, value: float, unit: str = "",
                    when: str = "", note: str = "") -> ToolResult:
    """Record one measurement. `when` defaults to now; "yesterday" works."""
    from ..metrics import log_value

    out = log_value(metric, value, unit, at=when, source="manual", note=note)
    if not out.get("ok"):
        return ToolResult.failed(str(out.get("error")))
    return ToolResult(f"Recorded: {out['metric']} {out['value']:g} "
                      f"{out['unit']} at {out['at'][:16].replace('T', ' ')}.")


def forget_measurement(metric: str, when: str = "") -> ToolResult:
    """Remove readings — for a value that was entered wrong.

    Without `when` it removes every manually-logged reading for that metric,
    which is a big enough action that the result says exactly how many went.
    """
    from ..metrics import forget, resolve

    found = resolve(metric)
    if found is None:
        return ToolResult.failed(f"“{metric}” is not something I track.")

    gone = forget(found.name, at=when, source="manual")
    if not gone:
        return ToolResult.failed(
            f"No manually-logged {found.name} reading"
            f"{' on ' + when if when else ''} to remove. Readings imported from "
            "a device are left alone — re-import to correct those.")
    where = f" on {when}" if when else ""
    return ToolResult(f"Removed {gone} {found.name} reading(s){where}.")
