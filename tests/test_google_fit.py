"""Reading a Google Takeout export of Google Fit.

There is no API left to use. The Fit REST API was deprecated on 1 May 2024 and
closed to new signups the same day; Health Connect, its replacement for device
data, is Android-only and on-device; and the Google Health API is Fitbit's, not
Fit's. So the only path from a Mac is the export the user asks for — the same
shape Apple Health already uses, which is why the bookkeeping is shared.

Two columns are deliberately not imported, and those are the tests that matter
most: both would have been wrong rather than merely imprecise, and wrong in a
way nobody would notice for months.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from lodestone import metrics
from lodestone.connectors import get_connector

#: A Daily Summaries.csv in Takeout's real shape, including the columns we
#: refuse and a zero-filled day.
SUMMARIES = """Date,Move Minutes count,Calories (kcal),Distance (m),Heart Points,Average heart rate (bpm),Max heart rate (bpm),Min heart rate (bpm),Step count,Average weight (kg),Sleep duration (ms)
2026-09-01,64,2480.5,6200,18,72,141,54,8400,78.4,25200000
2026-09-02,31,2210.0,3100,7,70,120,52,4100,78.1,21600000
2026-09-03,0,0,0,0,0,0,0,0,0,0
"""


@pytest.fixture
def takeout(tmp_path) -> Path:
    path = tmp_path / "takeout.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Takeout/Fit/Daily activity metrics/Daily Summaries.csv", SUMMARIES)
        archive.writestr("Takeout/archive_browser.html", "<html></html>")
    return path


@pytest.fixture(autouse=True)
def clean():
    yield
    for name in metrics.known():
        metrics.forget(name)


@pytest.fixture
def imported(takeout):
    result = get_connector("google_fit").sync(path=str(takeout))
    assert not result.errors, result.errors
    return result


def _values(metric):
    return [(round(r["value"], 3), r["at"][:10])
            for r in metrics.history(metric, days=36500)]


# ── it needs pointing at something ───────────────────────────────────────
def test_it_says_where_to_get_the_export():
    ready, reason = get_connector("google_fit").is_configured()
    assert not ready
    assert "takeout.google.com" in reason


def test_the_wrong_zip_says_what_to_download(tmp_path):
    other = tmp_path / "photos.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("Takeout/Photos/img.json", "{}")
    result = get_connector("google_fit").sync(path=str(other))
    assert result.errors
    assert "tick Fit" in result.errors[0]


def test_it_never_runs_on_the_background_timer():
    """A Takeout only changes when the user asks for a new one."""
    assert get_connector("google_fit").auto_sync is False


# ── what comes in ────────────────────────────────────────────────────────
def test_steps_arrive_per_day(imported):
    assert _values("steps") == [(8400.0, "2026-09-01"), (4100.0, "2026-09-02")]


def test_metres_become_kilometres(imported):
    """The column is in metres and the store is in kilometres."""
    assert _values("distance") == [(6.2, "2026-09-01"), (3.1, "2026-09-02")]


def test_milliseconds_become_hours(imported):
    """Nothing else in the product measures anything in milliseconds."""
    assert _values("sleep") == [(7.0, "2026-09-01"), (6.0, "2026-09-02")]


def test_weight_arrives(imported):
    assert _values("weight") == [(78.4, "2026-09-01"), (78.1, "2026-09-02")]


def test_move_minutes_are_training_minutes(imported):
    assert _values("workout_minutes") == [(64.0, "2026-09-01"), (31.0, "2026-09-02")]


# ── the two refusals, which are the point ────────────────────────────────
def test_googles_calories_never_land_in_the_active_energy_series():
    """Google's figure includes basal metabolism; Apple's does not.

    Mixing them would make the series meaningless for anyone who changed
    device, and nothing on screen would say so.
    """
    result = get_connector("google_fit").sync(path=str(_zip_of(SUMMARIES)))
    assert not result.errors, result.errors
    assert _values("energy_out") == [], "an incompatible number joined the series"
    assert _values("energy_total") == [(2480.5, "2026-09-01"), (2210.0, "2026-09-02")]


def test_heart_rate_columns_are_not_read_as_resting_heart_rate(imported):
    """Min heart rate is close to resting and is not the same thing."""
    assert _values("resting_heart_rate") == []


def test_a_zero_filled_day_is_not_stored_as_a_real_zero(imported):
    """Takeout writes 0 for a day with no data, which would drag every average."""
    for metric in ("steps", "weight", "sleep", "distance"):
        assert all(day != "2026-09-03" for _value, day in _values(metric)), metric


# ── the second export ────────────────────────────────────────────────────
def test_re_importing_adds_nothing(takeout, imported):
    before = len(metrics.history("steps", days=36500))
    again = get_connector("google_fit").sync(path=str(takeout))
    assert again.added == 0, "a second Takeout doubled the data"
    assert len(metrics.history("steps", days=36500)) == before


def test_a_bare_summaries_csv_works_too(tmp_path):
    """Somebody will unzip it and hand us the one file they care about."""
    plain = tmp_path / "Daily Summaries.csv"
    plain.write_text(SUMMARIES)
    result = get_connector("google_fit").sync(path=str(plain))
    assert not result.errors, result.errors
    assert result.added > 0


def test_per_day_files_get_their_date_from_the_filename(tmp_path):
    """Takeout also writes YYYY-MM-DD.csv, with no Date column inside."""
    folder = tmp_path / "Takeout" / "Fit" / "Daily activity metrics"
    folder.mkdir(parents=True)
    (folder / "2026-08-15.csv").write_text(
        "Step count,Distance (m)\n5000,4000\n")
    result = get_connector("google_fit").sync(path=str(tmp_path))
    assert not result.errors, result.errors
    assert _values("steps") == [(5000.0, "2026-08-15")]


def _zip_of(text: str) -> Path:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "takeout.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Takeout/Fit/Daily activity metrics/Daily Summaries.csv", text)
    return path


# ── it shares the bookkeeping rather than repeating it ───────────────────
def test_both_exports_use_the_same_base():
    """The part that drifts when copied is the part that is shared."""
    from lodestone.connectors.export_file import ExportConnector

    for name in ("apple_health", "google_fit"):
        assert isinstance(get_connector(name), ExportConnector), name
