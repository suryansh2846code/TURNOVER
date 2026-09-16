"""macOS blocked us, and we told the user to go configure a terminal.

Messages, Apple Mail and Apple Calendar are the three connectors that need no
sign-in at all — they read files already on the Mac. They should be the easiest
sources in the product. Instead they were the ones that dead-ended, because each
said a slightly different version of:

    grant Full Disk Access to your terminal/app

A shipped `.app` has no terminal. The user is looking at an app called Lodestone
and being told to find something else, in a System Settings list of dozens of
applications, with no hint which one. Three spellings in three files also meant
the copy could be fixed in one place and still be wrong in two.

These pin the sentence, the one-click `fix` the card hangs a button on, and the
security property that makes opening that pane safe at all.
"""
from __future__ import annotations

from lodestone.connectors import permissions
from lodestone.connectors.apple_calendar import AppleCalendarConnector
from lodestone.connectors.apple_mail import AppleMailConnector
from lodestone.connectors.imessage import IMessageConnector

BLOCKED = [IMessageConnector, AppleMailConnector, AppleCalendarConnector]


def test_the_sentence_names_lodestone_and_not_a_terminal():
    text = permissions.full_disk_access_reason("Messages")
    assert "Lodestone" in text, "it does not say which app to switch on"
    assert "terminal" not in text.lower(), (
        "a shipped .app has no terminal — this sends the user looking for "
        "something that is not on their screen")
    assert "Full Disk Access" in text and "Privacy & Security" in text, (
        "it does not say where to go")
    assert "Messages" in text, "it does not say which source is blocked"


def test_every_blocked_connector_uses_the_shared_sentence():
    """One place, or the copy gets fixed in one file and stays wrong in two."""
    for cls in BLOCKED:
        source = cls.__module__.rsplit(".", 1)[-1]
        src = __import__(cls.__module__, fromlist=["x"])
        assert getattr(src, "permissions", None) is permissions, (
            f"{source} does not use the shared permissions module")


def test_a_blocked_connector_offers_a_one_click_fix(monkeypatch, tmp_path):
    """`fix` is what the card turns into a button. Without it the user reads
    what is wrong and still has to go find the pane by hand."""
    conn = IMessageConnector.__new__(IMessageConnector)
    conn.fix = None

    monkeypatch.setattr("lodestone.connectors.imessage.CHAT_DB",
                        tmp_path / "chat.db")
    (tmp_path / "chat.db").write_text("not a database")   # exists, unreadable

    ready, reason = conn.is_configured()

    assert ready is False
    assert conn.fix == permissions.FULL_DISK_ACCESS, (
        "the refusal is clearable by the user but says so to nobody")
    assert "Lodestone" in reason


def test_a_connector_that_is_merely_absent_offers_no_button(monkeypatch, tmp_path):
    """Not every refusal is a permission. "You have no Messages database" is
    information; offering Full Disk Access for it sends the user somewhere that
    cannot help."""
    conn = IMessageConnector.__new__(IMessageConnector)
    conn.fix = None
    monkeypatch.setattr("lodestone.connectors.imessage.CHAT_DB",
                        tmp_path / "absent.db")

    ready, _ = conn.is_configured()

    assert ready is False
    assert conn.fix is None, "a missing database is not a permissions problem"


def test_the_settings_pane_is_a_constant_not_a_parameter():
    """The desktop bridge opens this and takes no argument.

    `/api/open-browser` refuses every scheme but http(s) on purpose: handing the
    system opener an arbitrary scheme lets a page reach any URL handler any
    installed app registered. The fix for Full Disk Access must not become a
    reason to widen that — so the URL lives here, fixed, and the bridge method
    that opens it accepts nothing.
    """
    assert permissions.FULL_DISK_ACCESS_PANE.startswith("x-apple.systempreferences:")
    assert "Privacy_AllFiles" in permissions.FULL_DISK_ACCESS_PANE

    from lodestone.api.security import is_safe_external_url
    assert not is_safe_external_url(permissions.FULL_DISK_ACCESS_PANE), (
        "this URL must still be refused by the open-browser guard — if it "
        "passes, that guard has been widened and every custom scheme is open")


def test_the_bridge_method_takes_no_url(monkeypatch):
    """A bridge that accepted a URL would be the widened guard, moved."""
    import inspect

    from lodestone import desktop

    src = inspect.getsource(desktop.run_app)
    assert "def open_privacy_settings(self) -> bool:" in src, (
        "open_privacy_settings should take no arguments — a URL parameter here "
        "is /api/open-browser's refused scheme problem in a new place")
