"""Numbers that change over time, kept as numbers.

The Health agent was asked to "review honestly rather than encouragingly" and
given no way to know anything. Every weight, every workout, every hour of sleep
the user mentioned became a *memory* — prose in the same pile as their email —
and the only way back to it was recall. So "am I actually gaining?" was answered
by a model reading a few sentences it happened to retrieve and estimating. The
repo's own rule about this is already written down for the Inbox agent: a number
you estimated is a number you made up.

Three reasons this is its own store and not the brain:

* **Recall is linear in memory count.** `store.search()` runs on every agent
  turn at ~0.05 ms per memory (`docs/SCALING.md`). One Apple Health export is
  tens of thousands of readings; filed as memories they would put a second onto
  every turn of every agent, forever, to answer questions nobody asks by search.
* **The access pattern is a range, not a search.** Nothing here is ever looked
  up by similarity. It is "weight, last ninety days", which is an index.
* **Claims supersede; readings accumulate.** "Their goal weight is 60 kg" is a
  claim and belongs in `brain/canonical`. "They weighed 78.4 kg on Tuesday" is
  not superseded by Wednesday — both happened.

Deliberately general rather than `health.py`: the shape is a numeric series over
time, and the Money agent wants exactly the same thing. One store both can use
beats two that drift.

**One unit per metric, converted on the way in.** A series with kilograms and
pounds mixed into it is not a series, and every average over it is wrong. The
canonical unit is stored and reported; input is accepted in the usual spellings
and anything unrecognised is refused rather than assumed.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .config import get_settings
from .log import get_logger, suppressed

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id         TEXT PRIMARY KEY,
    metric     TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,
    at         TEXT NOT NULL,          -- ISO 8601, when it was MEASURED
    source     TEXT NOT NULL,          -- 'manual' | a connector name
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_measure_series ON measurements(metric, at);
-- Re-importing the same export must not double every number in it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_measure_dedup
    ON measurements(metric, at, source);
"""


@dataclass(frozen=True)
class Metric:
    """One thing that can be measured, and what it is measured in."""

    name: str
    unit: str
    #: Accepted input unit → multiplier into `unit`. The canonical unit maps to
    #: 1.0 and is listed like any other, so there is no special case.
    accepts: dict[str, float] = field(default_factory=dict)
    #: What it is, for a tool result a model reads.
    about: str = ""
    #: Does a daily total make sense (steps), or only a reading (weight)?
    cumulative: bool = False


_MASS = {"kg": 1.0, "kgs": 1.0, "kilo": 1.0, "kilos": 1.0, "kilogram": 1.0,
         "kilograms": 1.0, "lb": 0.45359237, "lbs": 0.45359237,
         "pound": 0.45359237, "pounds": 0.45359237}
_LENGTH_CM = {"cm": 1.0, "centimetre": 1.0, "centimeter": 1.0, "cms": 1.0,
              "in": 2.54, "inch": 2.54, "inches": 2.54,
              "ft": 30.48, "foot": 30.48, "feet": 30.48, "m": 100.0}
_DISTANCE = {"km": 1.0, "kms": 1.0, "kilometre": 1.0, "kilometer": 1.0,
             "m": 0.001, "metre": 0.001, "meter": 0.001, "metres": 0.001,
             "mi": 1.609344, "mile": 1.609344, "miles": 1.609344}
_DURATION_MIN = {"min": 1.0, "mins": 1.0, "minute": 1.0, "minutes": 1.0,
                 "h": 60.0, "hr": 60.0, "hrs": 60.0, "hour": 60.0,
                 "hours": 60.0, "s": 1 / 60, "sec": 1 / 60, "secs": 1 / 60,
                 "second": 1 / 60, "seconds": 1 / 60}
_DURATION_H = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0,
               "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60,
               "minutes": 1 / 60}
#: "steps" itself is not listed: `convert` always accepts a metric's own
#: unit, and writing the rule twice is how the two copies drift apart.
_COUNT = {"": 1.0, "count": 1.0}
_ENERGY = {"kcal": 1.0, "cal": 1.0, "calorie": 1.0, "calories": 1.0,
           "kj": 0.239006, "kilojoule": 0.239006, "kilojoules": 0.239006}
_GRAMS = {"g": 1.0, "gram": 1.0, "grams": 1.0, "oz": 28.349523, "ounce": 28.349523}
_PERCENT = {"%": 1.0, "percent": 1.0, "pct": 1.0, "": 1.0}
#: `count/min` is Apple Health's spelling of bpm.
_BPM = {"bpm": 1.0, "": 1.0, "count/min": 1.0, "beats/min": 1.0}


METRICS: dict[str, Metric] = {
    "weight": Metric("weight", "kg", _MASS, "body weight"),
    "body_fat": Metric("body_fat", "%", _PERCENT, "body fat percentage"),
    "waist": Metric("waist", "cm", _LENGTH_CM, "waist measurement"),
    "height": Metric("height", "cm", _LENGTH_CM, "height"),
    "steps": Metric("steps", "steps", _COUNT, "steps walked", cumulative=True),
    "sleep": Metric("sleep", "hours", _DURATION_H, "time asleep", cumulative=True),
    "resting_heart_rate": Metric("resting_heart_rate", "bpm", _BPM,
                                 "resting heart rate"),
    # Apple writes this one as "mL/min·kg", which is the same thing.
    "vo2max": Metric("vo2max", "ml/kg/min",
                     {"": 1.0, "ml/kg/min": 1.0, "ml/min·kg": 1.0,
                      "ml/min/kg": 1.0},
                     "cardio fitness (VO2 max)"),
    "energy_in": Metric("energy_in", "kcal", _ENERGY, "calories eaten",
                        cumulative=True),
    "energy_out": Metric("energy_out", "kcal", _ENERGY,
                         "active calories burned", cumulative=True),
    # Separate from `energy_out` on purpose. Apple reports active energy only;
    # Google Fit reports the total including basal metabolism. Both are real
    # and they are not the same number, so mixing them into one series would
    # make it meaningless for anyone who changed device.
    "energy_total": Metric("energy_total", "kcal", _ENERGY,
                           "total calories burned, including at rest",
                           cumulative=True),
    "protein": Metric("protein", "g", _GRAMS, "protein eaten", cumulative=True),
    "workout_minutes": Metric("workout_minutes", "min", _DURATION_MIN,
                              "time training", cumulative=True),
    "distance": Metric("distance", "km", _DISTANCE, "distance covered",
                       cumulative=True),
    "rpe": Metric("rpe", "/10", {"": 1.0, "/10": 1.0, "rpe": 1.0},
                  "how hard a session felt, 1-10"),
}

#: Other honest spellings of the same thing. A model will write "bodyweight"
#: and a user will type "body weight"; refusing either teaches nobody anything.
ALIASES = {
    "bodyweight": "weight", "body weight": "weight", "body_weight": "weight",
    "mass": "weight", "bodyfat": "body_fat", "body fat": "body_fat",
    "fat": "body_fat", "step": "steps", "step_count": "steps",
    "sleep_hours": "sleep", "hours_slept": "sleep", "asleep": "sleep",
    "rhr": "resting_heart_rate", "resting_hr": "resting_heart_rate",
    "heart_rate": "resting_heart_rate", "vo2": "vo2max", "vo2_max": "vo2max",
    "calories": "energy_in", "calories_in": "energy_in", "kcal": "energy_in",
    "intake": "energy_in", "calories_out": "energy_out",
    "active_energy": "energy_out", "burned": "energy_out",
    "tdee": "energy_total", "total_energy": "energy_total",
    "energy_expenditure": "energy_total",
    "protein_g": "protein", "training_minutes": "workout_minutes",
    "exercise_minutes": "workout_minutes", "exercise": "workout_minutes",
    "run": "distance", "ran": "distance", "effort": "rpe",
}

#: Bodyweight moves a kilo or two a day on water alone, so "last minus first"
#: is mostly noise and reads as a result. Below this many days of data the
#: smoothed trend is not reported at all rather than reported badly.
SMOOTHING_DAYS = 7
MIN_DAYS_FOR_TREND = 10

_DB: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        path = get_settings().home / "metrics.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _DB = sqlite3.connect(str(path), check_same_thread=False)
        _DB.row_factory = sqlite3.Row
        _DB.executescript(_SCHEMA)
    return _DB


# ── naming ───────────────────────────────────────────────────────────────
def resolve(name: str) -> Metric | None:
    """The metric this name means, or None."""
    key = str(name or "").strip().lower().replace("-", "_")
    if key in METRICS:
        return METRICS[key]
    spaced = key.replace("_", " ")
    for candidate in (key, spaced):
        if candidate in ALIASES:
            return METRICS[ALIASES[candidate]]
    return None


def known() -> list[str]:
    return sorted(METRICS)


def convert(metric: Metric, value: float, unit: str) -> tuple[float, str]:
    """`value` in the metric's own unit, or an explanation of why not.

    Refuses an unrecognised unit rather than assuming the canonical one. A
    silent assumption here turns 170 lb into 170 kg, which is not a rounding
    error — it is a different person.
    """
    spelling = str(unit or "").strip().lower().rstrip(".")
    # A metric always accepts what it is stored in. Leaving this to each
    # `accepts` map made `steps` refuse the string "steps", so every daily
    # total from Apple Health was dropped on the way in — and dropped quietly,
    # which is how it survived being written.
    if spelling == metric.unit.lower():
        return float(value), ""
    if spelling not in metric.accepts:
        accepted = ", ".join(sorted({u for u in metric.accepts if u})) or metric.unit
        return 0.0, f"“{unit}” is not a unit for {metric.name}. Use one of: {accepted}."
    return float(value) * metric.accepts[spelling], ""


# ── writing ──────────────────────────────────────────────────────────────
def log_value(metric: str, value: float, unit: str = "", *, at: str = "",
              source: str = "manual", note: str = "") -> dict:
    """Record one reading. Returns `{ok, ...}` — never raises for bad input."""
    found = resolve(metric)
    if found is None:
        return {"ok": False,
                "error": f"“{metric}” is not something I track. I can track: "
                         f"{', '.join(known())}."}
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"“{value}” is not a number."}

    converted, problem = convert(found, number, unit or found.unit)
    if problem:
        return {"ok": False, "error": problem}

    when = _stamp(at)
    row_id = uuid.uuid4().hex
    conn = _conn()
    conn.execute(
        "INSERT INTO measurements (id, metric, value, unit, at, source, note, "
        "created_at) VALUES (?,?,?,?,?,?,?,?) "
        # Same metric, same moment, same source is the same reading. An import
        # run twice must not double every number in it.
        "ON CONFLICT(metric, at, source) DO UPDATE SET value=excluded.value, "
        "note=excluded.note",
        (row_id, found.name, converted, found.unit, when, source or "manual",
         str(note or ""), datetime.now(UTC).isoformat()))
    conn.commit()
    return {"ok": True, "metric": found.name, "value": converted,
            "unit": found.unit, "at": when}


def log_many(rows: list[dict], *, source: str) -> dict:
    """Bulk insert for an import. Returns `{stored, refused}`.

    One transaction, because an Apple Health export is tens of thousands of
    rows and committing each would take minutes.

    A row we cannot read is skipped and **named**, never dropped in silence.
    One malformed reading must not kill an import of twenty thousand — but an
    import that quietly stores two thirds of a file is worse than one that
    fails, because nothing in the result says which third is missing.
    """
    conn = _conn()
    now = datetime.now(UTC).isoformat()
    payload = []
    refused: dict[str, int] = {}

    def refuse(why: str) -> None:
        refused[why] = refused.get(why, 0) + 1

    for row in rows:
        name = str(row.get("metric", ""))
        found = resolve(name)
        if found is None:
            refuse(f"“{name}” is not a metric we track")
            continue
        try:
            number = float(row.get("value"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            refuse(f"{found.name}: value was not a number")
            continue
        converted, problem = convert(found, number, str(row.get("unit") or found.unit))
        if problem:
            refuse(problem)
            continue
        payload.append((uuid.uuid4().hex, found.name, converted, found.unit,
                        _stamp(str(row.get("at") or "")), source,
                        str(row.get("note") or ""), now))
    if not payload:
        return {"stored": 0, "refused": refused}
    # How many rows the table actually gained, not how many were offered.
    # Re-importing an export upserts every row and adds none, and answering
    # "stored 24,000" to that is a number that means nothing.
    before = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.executemany(
        "INSERT INTO measurements (id, metric, value, unit, at, source, note, "
        "created_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(metric, at, source) DO UPDATE SET value=excluded.value",
        payload)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    for why, count in refused.items():
        log.warning("skipped %d reading(s) from %s - %s", count, source, why)
    return {"stored": after - before, "refused": refused}


def forget(metric: str, *, at: str = "", source: str = "") -> int:
    """Remove readings — a mistyped weight has to be correctable.

    Without this a fat-fingered `780` sits in the series forever, and every
    average over it is wrong in a way the user can see and cannot fix.
    """
    found = resolve(metric)
    if found is None:
        return 0
    query = "DELETE FROM measurements WHERE metric=?"
    args: list[object] = [found.name]
    if at:
        query += " AND at LIKE ?"
        args.append(f"{_stamp(at)[:10]}%")
    if source:
        query += " AND source=?"
        args.append(source)
    conn = _conn()
    cursor = conn.execute(query, args)
    conn.commit()
    return cursor.rowcount


# ── reading ──────────────────────────────────────────────────────────────
def history(metric: str, *, days: int = 90, limit: int = 400) -> list[dict]:
    """Readings for one metric, oldest first."""
    found = resolve(metric)
    if found is None:
        return []
    since = (datetime.now(UTC) - timedelta(days=max(1, days))).isoformat()
    rows = _conn().execute(
        "SELECT value, unit, at, source, note FROM measurements "
        "WHERE metric=? AND at>=? ORDER BY at LIMIT ?",
        (found.name, since, max(1, limit))).fetchall()
    return [dict(r) for r in rows]


def latest(metric: str) -> dict | None:
    found = resolve(metric)
    if found is None:
        return None
    row = _conn().execute(
        "SELECT value, unit, at, source, note FROM measurements "
        "WHERE metric=? ORDER BY at DESC LIMIT 1", (found.name,)).fetchone()
    return dict(row) if row else None


def tracked() -> list[dict]:
    """Which metrics actually have data, and how much."""
    rows = _conn().execute(
        "SELECT metric, COUNT(*) AS n, MIN(at) AS first, MAX(at) AS last "
        "FROM measurements GROUP BY metric ORDER BY metric").fetchall()
    return [dict(r) for r in rows]


def summarise(metric: str, *, days: int = 90) -> dict:
    """The arithmetic, done here rather than by a model reading a list.

    Reports the smoothed trend as well as the raw change, and says which is
    which. Bodyweight swings a kilo a day on water; "you are up 0.9 kg since
    Monday" from two raw readings is the single most common wrong conclusion in
    this whole domain, and an agent that repeats it is worse than one that says
    nothing.
    """
    found = resolve(metric)
    if found is None:
        return {"ok": False, "error": f"“{metric}” is not something I track."}

    rows = history(found.name, days=days, limit=5000)
    if not rows:
        return {"ok": True, "metric": found.name, "unit": found.unit, "n": 0,
                "detail": "No readings yet."}

    values = [r["value"] for r in rows]
    out: dict = {
        "ok": True,
        "metric": found.name,
        "unit": found.unit,
        "about": found.about,
        "n": len(rows),
        "first": {"value": values[0], "at": rows[0]["at"]},
        "last": {"value": values[-1], "at": rows[-1]["at"]},
        "min": min(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 3),
        "change": round(values[-1] - values[0], 3),
    }
    if found.cumulative:
        out["total"] = round(sum(values), 3)
        out["per_day"] = round(sum(values) / max(1, _span_days(rows)), 2)

    trend = _smoothed_trend(rows)
    if trend is not None:
        out["trend"] = trend
    else:
        out["trend_note"] = (
            f"Not enough spread to smooth — a trend needs about "
            f"{MIN_DAYS_FOR_TREND} days. The raw change over {len(rows)} "
            "reading(s) is day-to-day noise as much as anything.")
    return out


def _when(value: str) -> datetime:
    """A stored timestamp as a comparable datetime.

    Always timezone-aware. Mixing one naive datetime into this set makes every
    comparison raise, and the first version of `_smoothed_trend` swallowed that
    with `suppressed` and returned "not enough data" — a silent wrong answer,
    which is the failure mode this file exists to remove.
    """
    with suppressed("reading a stored measurement timestamp"):
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _span_days(rows: list[dict]) -> int:
    return max(1, (_when(rows[-1]["at"]) - _when(rows[0]["at"])).days + 1)


def _smoothed_trend(rows: list[dict]) -> dict | None:
    """First week's average against the last week's, and a per-week rate."""
    if _span_days(rows) < MIN_DAYS_FOR_TREND:
        return None
    first_at, last_at = _when(rows[0]["at"]), _when(rows[-1]["at"])
    window = timedelta(days=SMOOTHING_DAYS)
    early = [r["value"] for r in rows if _when(r["at"]) < first_at + window]
    late = [r["value"] for r in rows if _when(r["at"]) > last_at - window]
    if not early or not late:
        return None
    start = sum(early) / len(early)
    end = sum(late) / len(late)
    weeks = max(1.0, (last_at - first_at).days / 7)
    return {
        "from": round(start, 2),
        "to": round(end, 2),
        "change": round(end - start, 2),
        "per_week": round((end - start) / weeks, 3),
        "basis": f"{SMOOTHING_DAYS}-day averages at each end, "
                 f"{len(early)} and {len(late)} readings",
    }


def _stamp(value: str) -> str:
    """When a reading was taken. Now, if nothing usable was given."""
    raw = str(value or "").strip()
    if raw:
        with suppressed("reading the time a measurement was taken"):
            return _aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        with suppressed("reading a plain date a measurement was taken"):
            from .core.dateparse import parse_date_range

            start, _end = parse_date_range(raw)
            if start:
                # `parse_date_range` answers in plain dates, and a bare date
                # stored beside a full timestamp is the naive/aware mix that
                # breaks every comparison downstream.
                return _aware(datetime.fromisoformat(start))
    return datetime.now(UTC).isoformat()


def _aware(moment: datetime) -> str:
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).isoformat()
