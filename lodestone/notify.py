"""Desktop notifications (native OS popup)."""
from __future__ import annotations

import shutil
import subprocess


def desktop_notify(title: str, message: str) -> bool:
    """Show a native desktop notification. macOS (osascript) or Linux
    (notify-send). Returns True if a notifier was invoked."""
    title = (title or "Lodestone")[:120]
    message = (message or "")[:400]
    if shutil.which("osascript"):
        t = title.replace('"', "'")
        m = message.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{m}" with title "{t}" sound name "default"'],
            capture_output=True)
        return True
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, message], capture_output=True)
        return True
    return False
