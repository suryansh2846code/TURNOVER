"""A spent plan limit is a wait, not an answer.

The Claude CLI reports a session limit with `is_error` AND a `result` string —
"5-hour session limit · resets 12am (Asia/Calcutta)". `claude_code.chat()`
returned that as the reply, so it landed in the transcript styled exactly like
something the model had said: no retry, no indication of how long to wait, and a
wall-clock time that is wrong for a reader in another timezone and wrong for
anyone who reopens the chat tomorrow.

One user's response was to type the word "retry" into the chat. That is what a
screen that offers nothing teaches people to do.
"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from chitragupta.models.errors import (
    ErrorKind,
    ProviderError,
    is_limit_notice,
    parse_reset_at,
)

ROOT = Path(__file__).parent.parent
CHAT_JS = ROOT / "chitragupta/web/chat.js"

NOTICE = "5-hour session limit · resets 12am (Asia/Calcutta)"
#: 11:10pm in Calcutta — so "12am" is fifty minutes away, not yesterday.
NOW = datetime(2026, 9, 18, 17, 40, tzinfo=UTC)


# ── the backend stops calling it an answer ────────────────────────────────
def test_a_limit_notice_is_recognised():
    assert is_limit_notice(NOTICE) is True
    assert is_limit_notice("Here is your answer about steps and calories.") is False


def test_a_wall_clock_time_becomes_the_next_time_it_reads_that():
    """"resets 12am" written at 11pm means in one hour, not twenty-three hours
    ago — and it is resolved in the zone the notice names, not ours."""
    reset = parse_reset_at(NOTICE, now=NOW)
    assert reset is not None
    local = reset.astimezone(ZoneInfo("Asia/Calcutta"))
    assert (local.hour, local.minute) == (0, 0)
    assert 0 < (reset - NOW).total_seconds() <= 3600


@pytest.mark.parametrize("text,minutes", [
    ("limit reached · resets in 3h 20m", 200),
    ("usage limit · resets in 45m", 45),
    ("session limit · resets in 1d", 1440),
])
def test_a_relative_reset_is_read_as_an_offset(text, minutes):
    reset = parse_reset_at(text, now=NOW)
    assert round((reset - NOW).total_seconds() / 60) == minutes


def test_a_notice_that_names_no_time_says_so():
    """Absent is reported as absent. The card then shows the sentence with no
    countdown rather than a made-up one."""
    assert parse_reset_at("usage limit reached", now=NOW) is None


def test_the_reply_carries_the_instant_not_the_providers_phrasing():
    err = ProviderError(kind=ErrorKind.RATE_LIMIT, provider="claude-code",
                        message=NOTICE, retryable=True,
                        retry_at=parse_reset_at(NOTICE, now=NOW).isoformat())
    reply = err.as_reply()
    assert reply.startswith('<limit until="')
    assert NOTICE in reply


def test_a_limit_is_no_longer_returned_as_a_normal_reply():
    """The regression, at its source: `if text: return ChatResult(text=text)`
    ran before anything looked at what the text said."""
    src = (ROOT / "chitragupta/models/claude_code.py").read_text()
    guard = src.index("is_limit_notice(text)")
    passthrough = src.index("# Claude returned a usable message anyway")
    assert guard < passthrough, "the limit check must run before the passthrough"


# ── the card the reader gets ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def card() -> dict:
    proc = subprocess.run(["node", str(ROOT / "tests/js/limit_card.mjs"), str(CHAT_JS)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_the_marker_never_reaches_the_screen(card):
    assert card["hasMarkerLeft"] is False
    assert card["parsed"] == NOTICE


def test_it_counts_down_rather_than_printing_a_clock_time(card):
    assert card["countdown"] == "Available again in 2h 30m"
    assert card["nearEnd"] == "Available again in 30s"


def test_retry_is_dead_until_the_wait_is_over(card):
    assert card["retryDisabled"] is True
    assert card["afterReset"] == "You can try again now."
    assert card["retryArmed"] is True


def test_it_does_not_repaint_once_a_second_for_three_hours(card):
    """A card that animates for three hours is a card nobody asked to animate."""
    assert card["tickMs"] == 10000


def test_an_ordinary_reply_is_not_a_limit_card(card):
    assert card["plain"] is True


def test_the_wait_is_written_the_way_a_person_says_it(card):
    assert card["labels"] == ["2h 30m", "5m 0s", "42s"]
