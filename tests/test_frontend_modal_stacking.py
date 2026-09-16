"""A modal has to be on top of whatever opened it.

"+ Add a connector" and "+ Connect a custom app" reported as broken. They were
not: the click fired, the modal was built and un-hidden — and then painted
*behind* the full-screen page the button was on, because `.modal-bg` was
`z-index: 50` while the settings and brain screens are `70`. The same thing was
already true of the drawer at `55`, so a modal opened from the connectors
drawer had always been sitting under a translucent backdrop that swallowed its
clicks.

Comparing the numbers in the stylesheet would catch this, but only for the
values it knows to compare, and it cannot see a stacking context created some
other way. So this asks the browser the question the user is really asking:
**if I click in the middle of the modal, do I hit the modal?**
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "chitragupta/web"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

#: Every overlay that can be open when a modal is raised, and the element whose
#: centre must still belong to the modal once it is.
UNDERNEATH = ["modelScreen", "brainScreen", "drawerBg"]

PROBE = """
<script>
window.addEventListener('load', () => {
  const out = {};
  const modal = document.querySelector('#brainModal');
  const card  = modal.querySelector('.modal');
  for (const id of UNDER_IDS) {
    document.querySelectorAll('.modal-bg, .drawer-bg, .modelscreen, .brainscreen')
      .forEach((el) => { el.hidden = true; });
    const under = document.getElementById(id);
    if (!under) { out[id] = 'missing'; continue; }
    under.hidden = false;                 // the page the button was clicked on
    modal.hidden = false;                 // …and the modal it opened
    const r = card.getBoundingClientRect();
    const hit = document.elementFromPoint(Math.round(r.left + r.width / 2),
                                          Math.round(r.top + r.height / 2));
    out[id] = hit ? (modal.contains(hit) ? 'modal' : (hit.id || hit.className || hit.tagName)) : 'nothing';
  }
  console.log('STACK ' + JSON.stringify(out));
});
</script>
"""
PROBE = PROBE.replace("UNDER_IDS", json.dumps(UNDERNEATH))


def _find_chrome() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return shutil.which("chromium") or shutil.which("google-chrome")


@pytest.fixture(scope="module")
def hits() -> dict:
    chrome = _find_chrome()
    if not chrome:
        pytest.skip("no headless-capable browser on this machine")

    html = (WEB / "index.html").read_text()
    html = re.sub(r"<script\b[^>]*\bsrc=[^>]*>\s*</script>", "", html)
    html = html.replace('href="/static/styles.css"', f'href="{(WEB / "styles.css").as_uri()}"')
    html = html.replace('href="styles.css"', f'href="{(WEB / "styles.css").as_uri()}"')
    # The modal needs some size to have a centre worth hit-testing.
    html = html.replace('<div id="bmBody"', '<div id="bmBody" style="min-height:260px"', 1)
    html = html.replace("</body>", PROBE + "</body>")

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "stack.html"
        page.write_text(html)
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--allow-file-access-from-files", "--virtual-time-budget=3000",
             "--window-size=1400,900", "--enable-logging=stderr", "--v=0",
             page.as_uri()],
            capture_output=True, text=True, timeout=90,
        )
    for line in proc.stderr.splitlines():
        if "STACK " in line:
            blob = line.split("STACK ", 1)[1]
            return json.loads(blob[: blob.rindex("}") + 1])
    pytest.fail(f"the probe never reported:\n{proc.stderr[-2000:]}")


@pytest.mark.parametrize("underneath", UNDERNEATH)
def test_a_modal_is_clickable_over_whatever_opened_it(hits, underneath):
    got = hits[underneath]
    assert got == "modal", (
        f"with #{underneath} open, the centre of the modal belongs to {got!r} — "
        "the modal is painted behind it, so the button that opened it looks "
        "like it did nothing"
    )
