"""The workspace's JavaScript, for tests that read it rather than run it.

Several tests grep the frontend source — for `prefers-reduced-motion`, for the
paths it calls, for an escaping invariant. They all used to read `app.js`,
because `app.js` was the whole app. It is not any more, and a test that greps
one of several files fails in the worst way: it passes.

The set and the order come from `index.html`, exactly as they do for the node
harnesses (`tests/js/_app_source.mjs`). The page is the single source of truth
about which scripts the app is made of; this module and that one both read it,
and `test_frontend_source_loader.py` asserts the two agree — so the duplicated
five lines of regex cannot drift on anything that matters.

Use `app_source()` when you want the app's JavaScript. Use `WEB / "app.js"`
only when you specifically mean that one file.
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).parent.parent / "chitragupta/web"

#: `<script src="/static/core.js">` — local sources only, in document order.
_SCRIPT_TAG = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>""",
                         re.IGNORECASE)


def app_scripts() -> list[pathlib.Path]:
    """The scripts `index.html` loads, in the order it loads them."""
    html = (WEB / "index.html").read_text()
    out = []
    for src in _SCRIPT_TAG.findall(html):
        if re.match(r"^(?:[a-z]+:)?//", src, re.IGNORECASE):
            continue                       # not ours to read
        out.append(WEB / src.removeprefix("/static/").lstrip("/"))
    return out


def app_source() -> str:
    """Those scripts concatenated — what the browser ends up executing.

    Joined on a newline so the last line of one file cannot be glued to the
    first line of the next.
    """
    return "\n".join(p.read_text() for p in app_scripts())
