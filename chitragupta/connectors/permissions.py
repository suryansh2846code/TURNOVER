"""macOS privacy gates, and how to tell the user about one.

Three connectors — Messages, Apple Mail, Apple Calendar — read files macOS
protects behind **Full Disk Access**. They are also the three connectors that
need no sign-in at all, so they ought to be the easiest sources in the product.
Instead they were the ones that dead-ended, because each said some version of:

    grant Full Disk Access to your terminal/app

In a shipped `.app` there is no terminal. The user is looking at an app called
Chitragupta and being told to find something else, in a list of dozens of
applications, with no idea which. Three connectors said it three slightly
different ways, so fixing the words meant finding all three.

This module is the one place that sentence exists, and the one place that knows
which System Settings pane clears it.

**On opening that pane.** The URL below is a custom scheme, and
`/api/open-browser` refuses every scheme but `http(s)` — deliberately, because
handing the system opener an arbitrary scheme lets a page reach any URL handler
any installed app registered. That guard is right and is not to be widened. The
desktop bridge (`desktop.py::_AppBridge.open_privacy_settings`) opens this
constant instead, and takes no argument, so there is nothing for a caller to
point somewhere else.
"""
from __future__ import annotations

#: Stable key the frontend switches on to offer a one-click fix. Sent on the
#: connector payload as `fix`; `None` means there is nothing to click.
FULL_DISK_ACCESS = "full_disk_access"

#: The System Settings pane that grants it. A constant, never a parameter.
FULL_DISK_ACCESS_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
)


def full_disk_access_reason(source: str) -> str:
    """What the user reads when macOS blocked us, not the connector.

    `source` names the thing in the user's words — "Messages", "Apple Mail" —
    because "the connector is not configured" describes our model of the
    problem and not theirs. The sentence says who blocked it, where to go, and
    what to switch on; the UI pairs it with a button that opens that pane.
    """
    return (
        f"macOS is blocking access to your {source}. Open System Settings → "
        "Privacy & Security → Full Disk Access, turn on Chitragupta, then try again."
    )
