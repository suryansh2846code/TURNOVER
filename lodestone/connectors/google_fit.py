"""Google Fit — the user's Takeout export, because the API is gone.

There is no live API to use, and this is not a gap we can close by trying
harder:

* The **Google Fit REST API** was deprecated on 1 May 2024 and closed to new
  signups the same day. Nobody who is not already using it can start.
* **Health Connect**, its replacement for device data, is Android-only and
  **on-device**. There is no server to call from a Mac.
* The **Google Health API** — the other migration target — is the former Fitbit
  Web API. It reaches Fitbit accounts, not Google Fit.

So the reachable path is the same one Apple Health uses: the export the user
asks for. Google Takeout produces *Fit → Daily activity metrics →
Daily Summaries.csv*, one row per day, which suits a daily aggregate store
exactly. All the bookkeeping is `ExportConnector`; this file is the parse.

Two columns are deliberately **not** imported, and both would have been wrong
rather than merely imprecise:

* **"Calories (kcal)"** is total expenditure *including* basal metabolism.
  Apple's `ActiveEnergyBurned` excludes it. Putting both into `energy_out`
  would make the series meaningless for anyone who ever changed device, so
  Google's figure goes to `energy_total` — a different, real quantity — and
  the two never mix.
* **"Average heart rate"** and **"Min heart rate"** are not resting heart rate.
  Min is close and is not the same, and quietly filing it as resting HR is the
  sort of silent wrongness this whole store exists to remove.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from ..log import get_logger, suppressed
from .export_file import ExportConnector

log = get_logger(__name__)

#: Takeout's column headings → our metric and the unit the column is in.
#: Headings have shifted spelling between Takeout versions, so matching is
#: case-insensitive and on a normalised key rather than the literal string.
COLUMNS: dict[str, tuple[str, str]] = {
    "step count": ("steps", "count"),
    "distance (m)": ("distance", "m"),
    "move minutes count": ("workout_minutes", "min"),
    "average weight (kg)": ("weight", "kg"),
    "calories (kcal)": ("energy_total", "kcal"),
    "sleep duration (ms)": ("sleep", "ms"),
}

#: Milliseconds are not a unit any metric accepts, and should not be — nothing
#: else in the product measures anything in them. Converted here, at the edge
#: that produces them.
_MS_TO_HOURS = 1 / 3_600_000

#: Where Takeout puts it. Matched loosely because the folder is localised and
#: the exact path has changed between versions.
DAILY_DIR = "daily activity metrics"

#: How often to check the stop flag. A Takeout can hold a file per day for
#: years, so this is per file rather than per row.
CHECK_EVERY = 50


class GoogleFitConnector(ExportConnector):
    name = "google_fit"
    label = "Google Fit"

    SETUP_HINT = ("choose your Google Takeout export — at takeout.google.com, "
                  "select Fit, then point us at the zip it emails you")
    NOT_OURS = ("That file is not a Google Takeout export with Fit in it. At "
                "takeout.google.com, tick Fit and download the zip.")

    def _read(self, source: Path, *, cancel=None,
              progress=None) -> tuple[list[dict], bool]:
        rows: list[dict] = []
        stopped = False

        for index, (name, text) in enumerate(_daily_files(source)):
            if cancel is not None and cancel.is_set():
                stopped = True
                break
            if progress is not None and index % CHECK_EVERY == 0:
                progress(index, 0, f"{index} day file(s) read")
            rows.extend(_read_csv(text, name))

        if not rows and not stopped:
            # Nothing at all matched: either the wrong zip, or Fit was not
            # ticked. Saying which is more use than "nothing found".
            raise ValueError(self.NOT_OURS)
        return rows, stopped


def _daily_files(source: Path):
    """(name, text) for each daily-metrics CSV, out of the zip or a folder."""
    if source.is_dir():
        for path in sorted(source.rglob("*.csv")):
            if DAILY_DIR in str(path).lower():
                with suppressed("reading one Google Fit day file"):
                    yield path.name, path.read_text(encoding="utf-8", errors="replace")
        return

    if source.suffix.lower() == ".csv":
        # Somebody will hand us Daily Summaries.csv on its own.
        with suppressed("reading a Google Fit summary file"):
            yield source.name, source.read_text(encoding="utf-8", errors="replace")
        return

    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if lowered.endswith(".csv") and DAILY_DIR in lowered:
                with suppressed("reading one file out of the Takeout zip"):
                    yield name, archive.read(name).decode("utf-8", errors="replace")


def _read_csv(text: str, filename: str) -> list[dict]:
    """Every reading in one daily-metrics CSV.

    Takeout writes both `Daily Summaries.csv` (a Date column, one row per day)
    and `YYYY-MM-DD.csv` (rows within one day, the date only in the filename).
    Both are handled, because a user pointed at the folder gets both.
    """
    out: list[dict] = []
    fallback_date = _date_from_name(filename)

    reader = csv.DictReader(io.StringIO(text))
    for record in reader:
        day = _day_of(record) or fallback_date
        if not day:
            continue
        for heading, raw in record.items():
            found = COLUMNS.get(str(heading or "").strip().lower())
            if not found or raw in (None, ""):
                continue
            metric, unit = found
            with suppressed("reading one Google Fit value"):
                value = float(raw)
                if not value:
                    # Takeout writes 0 for a day with no data of that kind.
                    # Storing it as a real zero would drag every average down.
                    continue
                if unit == "ms":
                    value, unit = value * _MS_TO_HOURS, "hours"
                out.append({"metric": metric, "value": value, "unit": unit,
                            "at": f"{day}T00:00:00+00:00",
                            "note": "daily total"})
    return out


def _day_of(record: dict) -> str:
    for key in ("Date", "date", "Day"):
        value = str(record.get(key) or "").strip()
        if len(value) >= 10:
            return value[:10]
    return ""


def _date_from_name(filename: str) -> str:
    """`2026-09-01.csv` → `2026-09-01`."""
    stem = Path(filename).stem
    parts = stem.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return stem
    return ""
