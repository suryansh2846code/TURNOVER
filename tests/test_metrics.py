"""Numbers that change over time, kept as numbers.

The Health agent was told to "review honestly rather than encouragingly" and
given nothing to review: every weight and every hour of sleep became prose in
the brain, and the only way back was recall. So progress was answered by a model
reading a few retrieved sentences and estimating.

Most of what is pinned here is about being wrong in a way nobody notices —
a pound stored as a kilo, a daily total silently refused, a raw two-reading
"trend" presented as a result.

Storage decisions: lodestone/metrics.py
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lodestone import metrics


@pytest.fixture(autouse=True)
def clean():
    """Each test owns the store. It is keyed to the temp home conftest sets."""
    yield
    for name in metrics.known():
        metrics.forget(name)


def _series(metric, values, *, start_days_ago=30, source="test", unit=""):
    # Midnight, not `now()`: two calls a microsecond apart would otherwise
    # produce different timestamps and the dedup test would measure the clock
    # rather than the unique index.
    base = (datetime.now(UTC) - timedelta(days=start_days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    rows = [{"metric": metric, "value": v, "unit": unit,
             "at": (base + timedelta(days=i)).isoformat()}
            for i, v in enumerate(values)]
    return metrics.log_many(rows, source=source)


# ── units: the one that is silently catastrophic ─────────────────────────
def test_pounds_become_kilograms():
    """170 lb stored as 170 kg is not a rounding error, it is another person."""
    out = metrics.log_value("weight", 170, "lb")
    assert out["ok"]
    assert out["unit"] == "kg"
    assert 77.0 < out["value"] < 77.2


def test_an_unknown_unit_is_refused_not_assumed():
    out = metrics.log_value("weight", 12, "stone")
    assert not out["ok"]
    assert "stone" in out["error"]
    assert metrics.history("weight") == [], "it stored it anyway"


def test_every_metric_accepts_the_unit_it_is_stored_in():
    """`steps` was stored as "steps" and refused "steps" on the way back in.

    Every daily total from Apple Health was dropped, quietly, which is how the
    bug survived being written.
    """
    for name, metric in metrics.METRICS.items():
        value, problem = metrics.convert(metric, 1.0, metric.unit)
        assert not problem, f"{name} does not accept its own unit {metric.unit!r}"
        assert value == 1.0, f"{name} rescales its own unit"


def test_the_names_people_actually_use_resolve():
    for spelling in ("bodyweight", "body weight", "BodyWeight", "mass"):
        assert metrics.resolve(spelling).name == "weight", spelling
    assert metrics.resolve("rhr").name == "resting_heart_rate"
    assert metrics.resolve("nonsense") is None


# ── the trend, which is the whole point ──────────────────────────────────
def test_a_trend_is_smoothed_not_first_minus_last():
    """Body weight swings a kilo a day. Two raw readings say almost nothing."""
    # A genuine +3 kg over 60 days, with daily water noise on top.
    values = [70 + i * 0.05 + (1.2 if i % 2 else -1.1) for i in range(60)]
    _series("weight", values, start_days_ago=60, unit="kg")

    summary = metrics.summarise("weight", days=90)
    assert summary["n"] == 60
    trend = summary["trend"]
    assert 2.0 < trend["change"] < 4.0, "the smoothed trend followed the noise"
    assert 0.2 < trend["per_week"] < 0.5
    assert "7-day averages" in trend["basis"], "it does not say what it is based on"


def test_two_readings_get_no_trend_at_all():
    """Better to say nothing than to present noise as a result."""
    metrics.log_value("weight", 80, "kg", at=(datetime.now(UTC) - timedelta(days=1)).isoformat())
    metrics.log_value("weight", 81, "kg")

    summary = metrics.summarise("weight", days=90)
    assert "trend" not in summary
    assert "trend_note" in summary
    assert "noise" in summary["trend_note"]


def test_a_bare_date_does_not_break_every_comparison():
    """A naive datetime mixed into the series made every comparison raise.

    `suppressed` swallowed it and the trend came back "not enough data" — a
    silent wrong answer, which is the failure this module exists to remove.
    """
    metrics.log_value("weight", 80, "kg", at="yesterday")
    stored = metrics.history("weight")[0]["at"]
    assert datetime.fromisoformat(stored).tzinfo is not None, (
        "a bare date was stored without a timezone")

    values = [70 + i * 0.05 for i in range(30)]
    _series("weight", values, start_days_ago=60, unit="kg")
    assert "trend" in metrics.summarise("weight", days=90)


def test_a_cumulative_metric_reports_a_total_and_a_daily_average():
    _series("steps", [8000, 12000, 4000], start_days_ago=3, unit="count")
    summary = metrics.summarise("steps", days=30)
    assert summary["total"] == 24000
    assert summary["per_day"] > 0


def test_a_point_metric_has_no_total():
    """Summing body weight is meaningless and would read as a number."""
    _series("weight", [80, 81], start_days_ago=2, unit="kg")
    assert "total" not in metrics.summarise("weight", days=30)


# ── importing twice ──────────────────────────────────────────────────────
def test_re_importing_the_same_export_does_not_double_anything():
    values = [70.0 + i for i in range(10)]
    first = _series("weight", values, unit="kg", source="apple_health")
    second = _series("weight", values, unit="kg", source="apple_health")

    assert first["stored"] == 10
    assert second["stored"] == 0, "a second import added rows"
    assert len(metrics.history("weight")) == 10


def test_a_refused_row_is_named_never_dropped_in_silence():
    """An import that quietly stores two thirds of a file looks like success."""
    out = metrics.log_many([
        {"metric": "weight", "value": 80, "unit": "kg"},
        {"metric": "weight", "value": 80, "unit": "furlongs"},
        {"metric": "chakra_alignment", "value": 3, "unit": ""},
        {"metric": "weight", "value": "heavy", "unit": "kg"},
    ], source="test")

    assert out["stored"] == 1
    assert len(out["refused"]) == 3, out["refused"]
    assert any("furlongs" in why for why in out["refused"])
    assert any("chakra_alignment" in why for why in out["refused"])


# ── correcting a mistake ─────────────────────────────────────────────────
def test_a_mistyped_reading_can_be_removed():
    """Otherwise a fat-fingered 780 poisons every average, visibly, forever."""
    metrics.log_value("weight", 78, "kg", at="2026-09-01")
    metrics.log_value("weight", 780, "kg", at="2026-09-02")
    assert metrics.summarise("weight", days=3650)["max"] == 780

    assert metrics.forget("weight", at="2026-09-02") == 1
    assert metrics.summarise("weight", days=3650)["max"] == 78


def test_forgetting_can_be_scoped_to_what_was_typed_in():
    """A device's readings are corrected by re-importing, not by deleting."""
    metrics.log_value("weight", 78, "kg", at="2026-09-01", source="manual")
    metrics.log_many([{"metric": "weight", "value": 79, "unit": "kg",
                       "at": "2026-09-02T00:00:00+00:00"}], source="apple_health")

    assert metrics.forget("weight", source="manual") == 1
    assert len(metrics.history("weight", days=3650)) == 1


# ── what exists ──────────────────────────────────────────────────────────
def test_tracked_says_what_there_is_data_for():
    _series("weight", [80, 81], start_days_ago=2, unit="kg")
    rows = {r["metric"]: r for r in metrics.tracked()}
    assert rows["weight"]["n"] == 2
    assert "sleep" not in rows


def test_an_empty_series_is_not_an_error():
    summary = metrics.summarise("sleep", days=30)
    assert summary["ok"] and summary["n"] == 0
