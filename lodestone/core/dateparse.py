"""Parse a date or date-range out of a natural-language query.

Turns phrases like "emails on July 14", "last week", "yesterday", "in August",
"2026-07-14" into an inclusive (start_iso, end_iso) pair for date-filtered
recall. Returns None when the query has no date intent.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _iso(d: date) -> str:
    return d.isoformat()


def parse_date_range(text: str, today: date | None = None) -> tuple[str, str] | None:
    """Return (start_iso, end_iso) inclusive, or None if no date is referenced."""
    t = text.lower()
    today = today or date.today()

    # explicit ISO date or range
    if m := re.search(r"(\d{4}-\d{2}-\d{2})", t):
        return m.group(1), m.group(1)

    # relative words
    if re.search(r"\byesterday\b", t):
        d = today - timedelta(days=1)
        return _iso(d), _iso(d)
    if re.search(r"\btoday\b", t):
        return _iso(today), _iso(today)
    if re.search(r"\btomorrow\b", t):
        d = today + timedelta(days=1)
        return _iso(d), _iso(d)
    if re.search(r"\b(this|current) week\b", t):
        start = today - timedelta(days=today.weekday())
        return _iso(start), _iso(start + timedelta(days=6))
    if re.search(r"\blast week\b", t):
        start = today - timedelta(days=today.weekday() + 7)
        return _iso(start), _iso(start + timedelta(days=6))
    if re.search(r"\b(past|last)\s+(\d+)\s+days?\b", t):
        n = int(re.search(r"(\d+)\s+days?", t).group(1))
        return _iso(today - timedelta(days=n)), _iso(today)
    if re.search(r"\bthis month\b", t):
        start = today.replace(day=1)
        end = today.replace(day=monthrange(today.year, today.month)[1])
        return _iso(start), _iso(end)
    if re.search(r"\blast month\b", t):
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return _iso(start), _iso(end)

    # "14 july", "july 14", optionally with a year
    day_month = re.search(r"\b(\d{1,2})\s+([a-z]+)\b", t)
    month_day = re.search(r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    year = None
    if ym := re.search(r"\b(20\d{2})\b", t):
        year = int(ym.group(1))
    for m, order in ((day_month, "dm"), (month_day, "md")):
        if not m:
            continue
        if order == "dm":
            day, mon = m.group(1), m.group(2)
        else:
            mon, day = m.group(1), m.group(2)
        if mon in _MONTHS:
            try:
                d = date(year or today.year, _MONTHS[mon], int(day))
                return _iso(d), _iso(d)
            except ValueError:
                pass

    # bare month name → whole month
    for name, num in _MONTHS.items():
        if len(name) > 3 and re.search(rf"\b{name}\b", t):
            y = year or today.year
            start = date(y, num, 1)
            end = date(y, num, monthrange(y, num)[1])
            return _iso(start), _iso(end)

    return None
