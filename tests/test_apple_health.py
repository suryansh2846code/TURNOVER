"""Reading the user's Apple Health export.

There is no API for this. HealthKit is iOS-only and the Health app does not
exist on macOS, so the export the Health app itself produces is the only path —
and it is the most local-first thing in the product: a file the user hands us,
read on their machine, no account involved.

What is pinned here is mostly the ways a health import is wrong without looking
wrong: a pound read as a kilo, time in bed counted as sleep, a body-fat fraction
read as a percentage, and a second import doubling a year of data.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from lodestone import metrics
from lodestone.connectors import get_connector

EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_GB">
 <ExportDate value="2026-09-16 10:00:00 +0000"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" startDate="2026-09-01 07:00:00 +0000" endDate="2026-09-01 07:00:00 +0000" value="78.4"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" unit="lb" startDate="2026-09-08 07:00:00 +0000" endDate="2026-09-08 07:00:00 +0000" value="174.2"/>
 <Record type="HKQuantityTypeIdentifierBodyFatPercentage" unit="%" startDate="2026-09-01 07:00:00 +0000" endDate="2026-09-01 07:00:00 +0000" value="0.184"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2026-09-01 09:00:00 +0000" endDate="2026-09-01 09:10:00 +0000" value="640"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2026-09-01 18:00:00 +0000" endDate="2026-09-01 18:20:00 +0000" value="2100"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2026-09-02 09:00:00 +0000" endDate="2026-09-02 09:10:00 +0000" value="900"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" unit="count/min" startDate="2026-09-01 07:00:00 +0000" endDate="2026-09-01 07:00:00 +0000" value="58"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisInBed" startDate="2026-09-01 22:00:00 +0000" endDate="2026-09-02 07:00:00 +0000"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2026-09-01 23:00:00 +0000" endDate="2026-09-02 03:00:00 +0000"/>
 <Record type="HKQuantityTypeIdentifierAudiogramSensitivity" unit="dB" startDate="2026-09-01 07:00:00 +0000" endDate="2026-09-01 07:00:00 +0000" value="12"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="32.5" durationUnit="min" totalDistance="5.2" totalDistanceUnit="km" startDate="2026-09-02 06:00:00 +0000" endDate="2026-09-02 06:32:00 +0000"/>
</HealthData>
"""


@pytest.fixture
def export(tmp_path) -> Path:
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("apple_health_export/export.xml", EXPORT)
    return path


@pytest.fixture(autouse=True)
def clean():
    yield
    for name in metrics.known():
        metrics.forget(name)


@pytest.fixture
def imported(export):
    result = get_connector("apple_health").sync(path=str(export))
    assert not result.errors, result.errors
    return result


def _values(metric):
    return [(round(r["value"], 3), r["at"][:10])
            for r in metrics.history(metric, days=3650)]


# ── it needs pointing at something ───────────────────────────────────────
def test_it_says_how_to_get_the_export():
    """A connector that just says "not configured" is a dead end."""
    ready, reason = get_connector("apple_health").is_configured()
    assert not ready
    assert "Export All Health Data" in reason


def test_a_file_that_is_not_an_export_says_so(tmp_path):
    bogus = tmp_path / "holiday.zip"
    bogus.write_bytes(b"not a zip at all")
    result = get_connector("apple_health").sync(path=str(bogus))
    assert result.errors
    assert "Apple Health export" in result.errors[0]


def test_it_never_runs_on_the_background_timer():
    """Re-parsing a gigabyte every thirty minutes to find nothing new."""
    assert get_connector("apple_health").auto_sync is False


# ── the readings ─────────────────────────────────────────────────────────
def test_pounds_are_converted(imported):
    weights = _values("weight")
    assert weights[0] == (78.4, "2026-09-01")
    assert 78.9 < weights[1][0] < 79.1, "174.2 lb was not read as kilograms"


def test_steps_are_totalled_per_day_not_stored_per_sample(imported):
    """Apple records steps in hundreds of samples a day."""
    assert _values("steps") == [(2740.0, "2026-09-01"), (900.0, "2026-09-02")]


def test_time_in_bed_is_not_counted_as_sleep(imported):
    """It would add an hour of lying awake to every night."""
    assert _values("sleep") == [(4.0, "2026-09-01")]


def test_a_body_fat_fraction_is_read_as_a_percentage(imported):
    """Apple writes 0.184 in some exports and 18.4 in others."""
    assert _values("body_fat") == [(18.4, "2026-09-01")]


def test_apples_own_unit_spellings_are_understood(imported):
    """`count/min` is how Apple writes bpm, and it used to be refused."""
    assert _values("resting_heart_rate") == [(58.0, "2026-09-01")]


def test_a_workout_contributes_its_length_and_distance(imported):
    assert _values("workout_minutes") == [(32.5, "2026-09-02")]
    assert _values("distance") == [(5.2, "2026-09-02")]


def test_what_we_do_not_track_is_skipped(imported):
    """Health records a hundred types; an audiogram is not training data."""
    assert metrics.resolve("audiogram") is None


# ── the second import ────────────────────────────────────────────────────
def test_re_importing_adds_nothing(export, imported):
    before = len(metrics.history("weight", days=3650))
    again = get_connector("apple_health").sync(path=str(export))

    assert again.added == 0, "a second export doubled the data"
    assert len(metrics.history("weight", days=3650)) == before


def test_the_chosen_export_is_remembered(export, imported):
    connector = get_connector("apple_health")
    ready, _reason = connector.is_configured()
    assert ready, "it forgot which file the user chose"


# ── it can be stopped ────────────────────────────────────────────────────
def test_a_plain_xml_file_works_too(tmp_path):
    """Somebody will unzip it first, and that is the same data."""
    plain = tmp_path / "export.xml"
    plain.write_text(EXPORT)
    result = get_connector("apple_health").sync(path=str(plain))
    assert not result.errors, result.errors
    assert result.added > 0
