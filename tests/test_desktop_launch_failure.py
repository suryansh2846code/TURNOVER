"""A launch that fails must say so, in the bundle where there is no terminal.

`run_app` reported a dead server with `print("Lodestone server failed to start.")`
and returned. That is fine in a checkout and worthless in a shipped `.app`: a
bundle is not launched from a shell, so stdout goes nowhere at all. The user
double-clicked the icon and *nothing happened* — no window, no dialog, not even
a dock bounce — which reads as a broken app and leaves nobody anything to act
on, least of all the person who has to debug it on someone else's Mac.

These pin the two halves of the fix: a frozen app reaches the native alert, and
the words in it name the log file rather than merely restating the failure.
"""
from __future__ import annotations

from pathlib import Path

from lodestone import desktop


def test_a_bundled_app_does_not_fail_silently(monkeypatch):
    """The whole bug: frozen, and the only report went to a stdout nobody has."""
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)

    shown: list[Path] = []
    monkeypatch.setattr(desktop, "_show_launch_failure_alert", shown.append)

    desktop.report_launch_failure()

    assert shown, (
        "a frozen app reported a failed launch to stdout only — from Finder "
        "that is indistinguishable from the app doing nothing at all")


def test_a_source_checkout_keeps_the_terminal_report(monkeypatch):
    """There IS a terminal here, and it already has the traceback. Popping a
    modal alert in front of a developer running `lodestone app` is noise."""
    monkeypatch.delattr(desktop.sys, "frozen", raising=False)

    shown: list[Path] = []
    monkeypatch.setattr(desktop, "_show_launch_failure_alert", shown.append)

    desktop.report_launch_failure()

    assert not shown, "a source checkout should not raise a native alert"


def test_the_alert_never_replaces_one_silence_with_another(monkeypatch, capsys):
    """If the alert itself explodes, the user must still get the print."""
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)

    def _explode(_path):
        raise RuntimeError("no AppKit here")

    monkeypatch.setattr(desktop, "_show_launch_failure_alert", _explode)

    desktop.report_launch_failure()      # must not raise

    assert "failed to start" in capsys.readouterr().out.lower()


def test_the_message_tells_the_user_what_to_do_next():
    """"Failed to start" alone is the same dead end, only louder."""
    log = Path("/Users/someone/Library/Lodestone/logs/lodestone.log")
    text = desktop.launch_failure_message(log)

    assert str(log) in text, "the message does not name the log file"
    assert "again" in text.lower(), "it does not suggest the obvious first step"
    # The alert is the entire explanation the user gets; it must not leak the
    # internals the rest of the product is careful to keep out of view.
    for internal in ("uvicorn", "Traceback", "127.0.0.1", "socket"):
        assert internal not in text, f"the alert exposes an internal: {internal}"
