"""A failure we survive is still a failure we should be able to see.

Much of this app does things that may legitimately fail: a locked Keychain, an
uninstalled vendor CLI, a provider nobody has connected. Written as
`try: … except Exception: pass`, each is correct at runtime and invisible
afterwards — which is how "it just doesn't work" becomes unfalsifiable, because
the one place that knew what went wrong discarded it.

`log.suppressed()` keeps the behaviour (nothing is raised) and keeps the
evidence. There were 58 silent handlers; this test is what stops there being 59.
"""
import ast
import logging
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "chitragupta"

# `log.py` defines the seam, so it cannot use it to guard its own file handler.
ALLOWED = {"log.py"}


def _silent_handlers(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            broad = h.type is None or getattr(h.type, "id", "") in ("Exception", "BaseException")
            if broad and len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                yield h.lineno


def test_no_failure_is_thrown_away_in_silence():
    offenders = [f"{p.relative_to(SRC.parent)}:{line}"
                 for p in sorted(SRC.rglob("*.py")) if p.name not in ALLOWED
                 for line in _silent_handlers(p)]
    assert not offenders, (
        "`except Exception: pass` discards the only record of what went wrong. "
        "Use `with suppressed('what you were attempting'):` from chitragupta.log "
        f"instead — {len(offenders)} site(s): {offenders[:6]}")


def test_suppressed_does_not_raise_and_does_record():
    """Captured with our own handler rather than pytest's `caplog`: the
    `chitragupta` logger does not propagate to the root, so the packaged app can
    never double-print through a host's logging config."""
    from chitragupta.log import get_logger, suppressed

    log = get_logger("tests.suppressed")
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _Capture()
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    try:
        with suppressed("reading a file that is not there", logger=log):
            open("/definitely/not/here")           # noqa: SIM115
    finally:
        log.removeHandler(handler)

    assert records, "the failure was suppressed and then lost anyway"
    assert "reading a file that is not there" in records[0]
    assert "No such file" in records[0]


def test_suppressed_lets_a_cancellation_through():
    """KeyboardInterrupt and SystemExit are not survivable failures. Swallowing
    them would make the app impossible to quit — `except BaseException: pass`
    in a loop is exactly that bug."""
    from chitragupta.log import suppressed

    with pytest.raises(KeyboardInterrupt), suppressed("a block the user interrupted"):
        raise KeyboardInterrupt

    with pytest.raises(SystemExit), suppressed("a block that asked to exit"):
        raise SystemExit(1)


def test_every_suppression_says_what_it_was_attempting():
    """A label of "" or "error" is the same as `pass` with extra steps."""
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                call = item.context_expr
                if (isinstance(call, ast.Call)
                        and getattr(call.func, "id", "") == "suppressed"):
                    arg = call.args[0] if call.args else None
                    label = arg.value if isinstance(arg, ast.Constant) else None
                    if not isinstance(label, str) or len(label.strip()) < 4:
                        bad.append(f"{path.relative_to(SRC.parent)}:{node.lineno}")
    assert not bad, f"suppression with no useful label: {bad}"


def test_logs_land_somewhere_a_bug_report_can_reach():
    """A user who hits a problem is not sitting in a terminal. Debug output goes
    to a rotating file under the Chitragupta home so there is something to read.

    Forced, because the directory can vanish under a running app — `/api/brain/
    reset` clears the Chitragupta home — and re-configuring has to put it back
    rather than quietly logging into nowhere for the rest of the session.
    """
    from chitragupta.config import get_settings
    from chitragupta.log import configure

    configure(force=True)
    assert (get_settings().home / "logs").is_dir()


def test_logging_survives_a_home_it_cannot_write(monkeypatch):
    """A log that cannot be written must never stop the app from starting."""
    from chitragupta import log as logmod

    monkeypatch.setattr(logmod, "_log_dir", lambda: None)
    logmod.configure(force=True)
    logmod.get_logger("tests.nowhere").warning("still fine")
