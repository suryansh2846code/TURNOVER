"""The log a user can read, and the reason there was nothing in it.

Two findings, one commit.

**`suppressed()` recorded nothing.** `log.py` exists so that a survivable
failure keeps its evidence — 107 call sites — and the root logger sat at INFO
unless `CHITRAGUPTA_DEBUG` was set. A logger discards a record below its own level
*before any handler sees it*, and `suppressed()` logs at DEBUG. So on every
machine belonging to someone who has not set an environment variable they have
never heard of, the file said nothing precisely when a bug report needed it to.

**And nobody could read it anyway.** The evidence went to a file a shipped
`.app` user cannot open, which makes "it just doesn't work" unfalsifiable in
exactly the cases it was written for. `/CLAUDE.md` forbids sending anyone to a
terminal; "open Console.app and find our file" is that instruction in a hat.
"""
from __future__ import annotations

import logging

import pytest
from starlette.testclient import TestClient

from chitragupta.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def written(tmp_path, monkeypatch):
    """A log file with known contents, in a home of our own."""
    directory = tmp_path / "logs"
    directory.mkdir(parents=True)
    path = directory / "chitragupta.log"
    monkeypatch.setattr("chitragupta.api.routes.diagnostics._log_file", lambda: path)
    return path


# ── the level bug: the evidence has to reach the file at all ──────────────
def test_a_suppressed_failure_is_recorded_without_an_env_var(tmp_path, monkeypatch):
    """The regression. This is the whole promise of `log.py`.

    Asserted through the real logger rather than by reading `setLevel`, because
    what matters is whether the line arrives — the level is the mechanism, not
    the behaviour.
    """
    from chitragupta import log as log_module

    monkeypatch.delenv("CHITRAGUPTA_DEBUG", raising=False)
    monkeypatch.setattr(log_module, "_log_dir", lambda: tmp_path)
    monkeypatch.setattr(log_module, "_configured", False)
    logging.getLogger("chitragupta").handlers.clear()
    log_module.configure(force=True)

    with log_module.suppressed("reading the saved port"):
        raise OSError("no such file")

    written_text = (tmp_path / "chitragupta.log").read_text()
    assert "reading the saved port" in written_text
    assert "no such file" in written_text


def test_debug_output_still_stays_off_the_terminal_by_default(tmp_path, monkeypatch):
    """The reason the level was wrong in the first place was a real concern: the
    desktop app's stdout is not a log viewer, and noise there trains people to
    ignore it. Recording everything must not mean printing everything."""
    from chitragupta import log as log_module

    monkeypatch.delenv("CHITRAGUPTA_DEBUG", raising=False)
    monkeypatch.setattr(log_module, "_log_dir", lambda: tmp_path)
    monkeypatch.setattr(log_module, "_configured", False)
    logging.getLogger("chitragupta").handlers.clear()
    log_module.configure(force=True)

    streams = [h for h in logging.getLogger("chitragupta").handlers
               if isinstance(h, logging.StreamHandler)
               and not hasattr(h, "baseFilename")]
    assert streams, "there is still a terminal handler"
    assert all(h.level == logging.WARNING for h in streams)


def test_debug_env_var_now_means_show_me_here(tmp_path, monkeypatch):
    """It used to decide what was *recorded*, which is why nothing was. It now
    decides what is *shown*, which is what someone setting it wants."""
    from chitragupta import log as log_module

    monkeypatch.setenv("CHITRAGUPTA_DEBUG", "1")
    monkeypatch.setattr(log_module, "_log_dir", lambda: tmp_path)
    monkeypatch.setattr(log_module, "_configured", False)
    logging.getLogger("chitragupta").handlers.clear()
    log_module.configure(force=True)

    streams = [h for h in logging.getLogger("chitragupta").handlers
               if isinstance(h, logging.StreamHandler)
               and not hasattr(h, "baseFilename")]
    assert all(h.level == logging.DEBUG for h in streams)


def test_the_log_path_is_named_once(tmp_path, monkeypatch):
    """The handler writes it and the endpoint reads it. Two spellings of the
    same path is a bug whose only symptom is an empty panel."""
    from chitragupta import log as log_module

    monkeypatch.setattr(log_module, "_log_dir", lambda: tmp_path)

    assert log_module.log_file() == tmp_path / log_module.LOG_FILENAME


def test_no_writable_home_means_no_log_file_rather_than_a_crash(monkeypatch):
    from chitragupta import log as log_module

    monkeypatch.setattr(log_module, "_log_dir", lambda: None)

    assert log_module.log_file() is None


# ── reading it back ──────────────────────────────────────────────────────
def test_recent_lines_come_back_oldest_first(client, written):
    """Reading order. A panel is read top to bottom and a sequence of events
    only makes sense in the order they happened."""
    written.write_text("first line\nsecond line\nthird line\n")

    body = client.get("/api/diagnostics/log").json()

    assert body["ok"] is True
    assert body["lines"] == ["first line", "second line", "third line"]


def test_blank_lines_are_dropped(client, written):
    """Tracebacks leave them, and they are half the height of the panel."""
    written.write_text("one\n\n\n   \ntwo\n")

    assert client.get("/api/diagnostics/log").json()["lines"] == ["one", "two"]


def test_only_the_tail_is_returned(client, written):
    written.write_text("".join(f"line {i}\n" for i in range(1000)))

    body = client.get("/api/diagnostics/log?lines=10").json()

    assert body["lines"] == [f"line {i}" for i in range(990, 1000)]
    assert body["truncated"] is True, "the user must know there is more above"


def test_a_short_file_is_not_reported_as_truncated(client, written):
    written.write_text("all of it\n")

    assert client.get("/api/diagnostics/log").json()["truncated"] is False


@pytest.mark.parametrize("asked", [0, -5, 100_000, 999999])
def test_an_absurd_line_count_is_clamped_not_refused(client, written, asked):
    """There is no request here worth a 400 — the panel asks for a number and
    gets the most we will send."""
    written.write_text("".join(f"line {i}\n" for i in range(2000)))

    body = client.get(f"/api/diagnostics/log?lines={asked}").json()

    assert body["ok"] is True
    assert 1 <= len(body["lines"]) <= 500


def test_a_very_large_file_does_not_return_all_of_it(client, written):
    """The file rotates at 2 MB. Rendering that into the DOM freezes the window,
    and reading it to keep the last 200 lines is work nobody asked for."""
    written.write_text("".join(f"line {i} " + "x" * 200 + "\n" for i in range(20_000)))

    body = client.get("/api/diagnostics/log?lines=500").json()

    assert len(body["lines"]) == 500
    assert body["lines"][-1].startswith("line 19999")


def test_a_seek_landing_mid_character_does_not_500(client, written):
    """Reading from the end of a UTF-8 file can start halfway through a
    multi-byte character. A diagnostics panel that fails on a stray byte is
    worse than one showing a replacement character."""
    written.write_bytes(("é" * 400_000).encode() + b"\nthe last line\n")

    body = client.get("/api/diagnostics/log").json()

    assert body["ok"] is True
    assert body["lines"][-1] == "the last line"


# ── secrets ──────────────────────────────────────────────────────────────
def test_a_token_in_an_exception_is_not_handed_back(client, written):
    """This panel exists to be copied into a bug report. The file was already on
    the user's disk; what is new is how easily its contents travel."""
    written.write_text(
        "2026-09-16 21:22:56,474 ERROR lodestone.gmail: 401 invalid "
        "Bearer ya29.a0AfB1234567890abcdefghijklmnop\n")

    line = client.get("/api/diagnostics/log").json()["lines"][0]

    assert "ya29.a0AfB1234567890abcdefghijklmnop" not in line
    assert "REDACTED" in line


@pytest.mark.parametrize("secret", [
    "xai-abcdefghijklmnopqrstuvwxyz123456",
    "ntn_1234567890abcdefghijklmnopqrst",
    "ghp_abcdefghijklmnopqrstuvwxyz1234",
    "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456",
])
def test_every_key_shape_this_app_handles_is_stripped(client, written, secret):
    written.write_text(f"ERROR lodestone.models: {secret} was rejected\n")

    assert secret not in client.get("/api/diagnostics/log").json()["lines"][0]


def test_the_ordinary_parts_of_a_line_survive_redaction(client, written):
    """Over-redacting into uselessness is the other way to fail. A timestamp, a
    port and a duration are what make a log readable."""
    written.write_text(
        "2026-09-16 21:22:56,474 INFO chitragupta.api: bound on 127.0.0.1:52341 "
        "after 1832ms\n")

    line = client.get("/api/diagnostics/log").json()["lines"][0]

    assert "2026-09-16 21:22:56,474" in line
    assert "127.0.0.1:52341" in line
    assert "1832ms" in line


# ── nothing to show ──────────────────────────────────────────────────────
def test_no_log_yet_says_so_rather_than_showing_an_empty_box(client, tmp_path, monkeypatch):
    """An empty panel reads as "nothing went wrong", which is a different and
    wrong answer."""
    monkeypatch.setattr("chitragupta.api.routes.diagnostics._log_file",
                        lambda: tmp_path / "absent.log")

    body = client.get("/api/diagnostics/log").json()

    assert body["ok"] is False
    assert body["lines"] == []
    assert "nothing has been recorded" in body["detail"].lower()


def test_a_machine_with_nowhere_to_write_logs_still_answers(client, monkeypatch):
    monkeypatch.setattr("chitragupta.api.routes.diagnostics._log_file", lambda: None)

    body = client.get("/api/diagnostics/log").json()

    assert body["ok"] is False
    assert body["path"] is None
    assert body["detail"]


def test_an_unreadable_log_is_reported_not_raised(client, written, monkeypatch):
    written.write_text("something\n")
    monkeypatch.setattr("chitragupta.api.routes.diagnostics._tail",
                        lambda p, n: (_ for _ in ()).throw(OSError("permission denied")))

    body = client.get("/api/diagnostics/log").json()

    assert body["ok"] is False
    assert "could not be read" in body["detail"]
