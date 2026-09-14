"""The harness loader must hand back exactly what the browser runs.

Every `tests/js/*.mjs` harness evaluates the workspace with `new Function(src)`,
which compiles a script and cannot process `import`. So when `app.js` is split
it becomes more classic `<script src>` tags sharing one scope in document order,
and the harnesses need the same concatenation the browser performs.

`_app_source.mjs` does that by reading the order out of `index.html`. These
tests pin the two properties the split depends on: it agrees with the page, and
while the app is one file it returns that file unchanged.

Read docs/development/frontend-testing.md before touching any of this.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"
LOADER = ROOT / "tests/js/_app_source.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _probe(expr: str) -> dict:
    """Run one expression against the loader and return its JSON result."""
    script = (
        f'import {{ appScripts, appSource }} from "{LOADER.as_posix()}";\n'
        f'const webDir = {json.dumps(str(WEB))};\n'
        f'process.stdout.write(JSON.stringify({expr}));\n'
    )
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[:500]
    return json.loads(proc.stdout)


def test_it_returns_the_scripts_index_html_actually_loads():
    """The order is the page's, not a list kept in the loader."""
    listed = [pathlib.Path(p).name for p in _probe("appScripts(webDir)")]
    html = (WEB / "index.html").read_text()
    for name in listed:
        assert f'src="/static/{name}"' in html, f"{name} is not loaded by index.html"
    assert "app.js" in listed, "the workspace's own script is missing"


def test_a_script_on_disk_that_the_page_never_loads_is_not_included():
    """The harness must load what the browser loads — including nothing.

    A module added to `lodestone/web/` but never wired into `index.html` is dead
    in the browser. A loader that globbed the directory would hide that; this
    one cannot.
    """
    orphan = WEB / "__loader_probe_unused.js"
    orphan.write_text("// not referenced by index.html\n")
    try:
        assert orphan.name not in [pathlib.Path(p).name
                                   for p in _probe("appScripts(webDir)")]
    finally:
        orphan.unlink()


def test_the_source_is_exactly_its_parts_and_nothing_else():
    """Concatenation adds nothing and drops nothing.

    This began life as "while app.js is one file, the source is that file
    unchanged" — the no-op property that made pointing nine harnesses at this
    loader safe to land on its own. app.js is three files now, so that wording
    could only ever skip. This is the same guarantee stated for any number of
    them: what the harnesses evaluate is the files the page lists, joined, with
    nothing invented in between.
    """
    scripts = [pathlib.Path(p) for p in _probe("appScripts(webDir)")]
    expected = "\n".join(p.read_text() for p in scripts)
    assert _probe("appSource(webDir)") == expected


def test_the_concatenation_cannot_glue_two_files_together():
    """Joined on a newline, so a file with no trailing newline stays separate."""
    scripts = [pathlib.Path(p) for p in _probe("appScripts(webDir)")]
    src = _probe("appSource(webDir)").splitlines()
    assert src, "loader returned nothing"
    # The seams: the first line of the first file and the last of the last must
    # survive intact, and every file's first line must appear somewhere.
    assert src[0] == scripts[0].read_text().splitlines()[0]
    assert src[-1] == scripts[-1].read_text().splitlines()[-1]
    for s in scripts:
        assert s.read_text().splitlines()[0] in src, f"{s.name} was fused or lost"


def test_python_and_node_agree_on_what_the_app_is_made_of():
    """Two loaders, one source of truth.

    `tests/web_sources.py` mirrors `_app_source.mjs` for tests that read the
    frontend instead of running it. Both parse `index.html`, so neither can
    invent an order — but this is what stops the two regexes drifting.
    """
    from web_sources import app_scripts, app_source

    assert [str(p) for p in app_scripts()] == _probe("appScripts(webDir)")
    assert app_source() == _probe("appSource(webDir)")


# ── the guard ────────────────────────────────────────────────────────────────

def test_no_test_reads_app_js_when_it_means_the_whole_frontend():
    """A grep of one file out of several passes for the wrong reason.

    `app.js` was the whole frontend, so tests that assert something about the
    workspace's JavaScript read it directly. It is not any more, and the failure
    that causes is the bad kind: when `providers.js` was extracted, eleven tests
    went red at once — and the ones that would have stayed green while checking
    nothing are the reason this guard exists rather than a note in a doc.

    Passing the path to a node harness is fine and stays fine: the harness
    derives the web directory from it and asks `_app_source.mjs` for the app.
    Only *reading* it here is the mistake, so only that is banned.
    """
    import re

    tests_dir = pathlib.Path(__file__).parent
    offenders = []
    reads_app_js = re.compile(r'app\.js"\s*\)?\s*\.read_text\(\)|app_js\s*=.*app\.js.*read_text')
    for path in sorted(tests_dir.glob("test_*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "app.js" in line and reads_app_js.search(line):
                offenders.append(f"{path.name}:{n}")

    assert not offenders, (
        "these read app.js directly; use `from web_sources import app_source` "
        f"so the whole frontend is checked: {offenders}")
