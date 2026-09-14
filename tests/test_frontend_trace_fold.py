"""The tool trace is folded away until asked for.

A turn that read six files used to put six blocks of raw JSON arguments
between the question and the answer — the trace was longer than the reply and
buried it. What an agent actually ran is worth being able to check; it is the
difference between trusting an answer and taking it on faith. It is just not
the answer, so it is a disclosure now.

`<details>` is the mechanism on purpose: the open/closed state belongs to the
browser, it is keyboard-operable without any code, and it cannot fall out of
step with a re-render the way a toggle flag can. But "folded" is a property of
the element `addTrace` creates, and a refactor can reopen it while every other
assertion still passes — so this runs addTrace and looks at what came out.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"

STEPS = []
for _name, _args in [
    ("Edit", {"file_path": "/Users/x/MEMORY.md", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "/Users/x/person.md", "content": "y" * 400}),
    ("Read", {"file_path": "/Users/x/person.md"}),
    ("Read", {"file_path": "/Users/x/other.md"}),
]:
    STEPS.append({"kind": "tool_call", "name": _name, "arguments": _args})
    STEPS.append({"kind": "tool_result", "name": _name, "result": f"Unknown tool: {_name}"})


def _run(steps) -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/trace_fold.mjs"), str(WEB / "app.js")],
        input=json.dumps(steps), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def trace() -> dict:
    return _run(STEPS)


def test_the_trace_is_a_disclosure(trace):
    assert trace["appended"] is True
    assert trace["tag"] == "details", (
        f"the trace is a <{trace['tag']}> — a plain element cannot be folded, "
        "and a hand-rolled toggle loses the keyboard behaviour <details> gives")


def test_it_starts_closed(trace):
    assert trace["open"] is False, (
        "the trace renders open, so a turn that ran six tools again puts six "
        "blocks of JSON between the question and the answer")


def test_the_fold_still_says_what_happened(trace):
    """A disclosure the user cannot judge from the outside just gets ignored."""
    summary = trace["html"].split("</summary>")[0]
    assert "Show thinking" in summary
    assert "4 steps" in summary
    for tool in ("Edit", "Write", "Read"):
        assert tool in summary, f"the summary does not name {tool}"


def test_opening_it_shows_every_call(trace):
    assert trace["html"].count('class="step"') == 4


def test_a_turn_that_ran_nothing_adds_nothing(trace):
    """An empty disclosure is a control that opens onto nothing."""
    assert _run([])["appended"] is False
    assert _run([{"kind": "tool_result", "name": "x", "result": "y"}])["appended"] is False


def test_the_tool_name_is_escaped():
    """It arrives from a model, so it is not ours to trust into innerHTML."""
    out = _run([{"kind": "tool_call", "name": "<img src=x onerror=alert(1)>", "arguments": {}}])
    assert "<img" not in out["html"]
    assert "&lt;img" in out["html"]
