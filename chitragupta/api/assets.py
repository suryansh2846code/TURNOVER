"""Where the frontend lives on disk.

Its own module so the route packages can find the web directory without
importing `app`, which imports them — the cycle that otherwise makes a router
split impossible to do cleanly.
"""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
