"""A turn carries the provider the user chose, even on the first message.

Two replies came back as a truncated echo of the recall block — the signature
of `MockProvider`, which calls search_brain and returns the tool result cut at
400 characters. They were not a model failing; they never reached a model.

The turn read `$("#provider").value`, a hidden `<select>` that is empty until
`loadProviders()` fills it — and that fetches the model catalog, measured cold
at roughly ten seconds. For those ten seconds the composer displayed the
provider from localStorage while the request carried nothing at all, the server
fell back to `settings.model_provider` (`mock` on a fresh install), and the
offline model answered dressed as a real one.

localStorage is where the picker actually writes, and it is readable on the
first paint. This pins that: the race window is what the fixture recreates.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"


def _turn(saved, select_value="") -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/turn_provider.mjs"), str(WEB / "app.js")],
        input=json.dumps({"saved": saved, "selectValue": select_value}),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_the_first_message_reaches_the_chosen_provider():
    """The select is empty — as it is for ~10s after every launch."""
    assert _turn("openai", select_value="")["sentProvider"] == "openai", (
        "the turn was sent with no provider while the catalog was still "
        "loading, so the server falls back to the offline model")


def test_the_users_choice_beats_the_stale_copy():
    """Both are set and disagree: localStorage is where the picker writes."""
    assert _turn("anthropic", select_value="openai")["sentProvider"] == "anthropic"


def test_the_select_still_works_when_nothing_is_saved():
    assert _turn(None, select_value="ollama")["sentProvider"] == "ollama"


def test_nothing_chosen_sends_nothing_rather_than_a_guess():
    """With no choice anywhere the server's own default is the right answer."""
    assert _turn(None, select_value="")["sentProvider"] is None


# ── the offline model no longer passes for a real one ─────────────────────
def test_the_offline_model_says_it_is_the_offline_model():
    """The two bad replies were prose in a chat bubble, indistinguishable from
    a real answer. Two of those in a row read as "the app is broken" rather
    than "nothing is connected yet" — a different problem with a different fix.
    """
    from lodestone.models.base import Message
    from lodestone.models.registry import get_provider

    reply = get_provider("mock").chat(
        [Message(role="tool", content="some recalled context")]).text
    assert reply.startswith("_Offline model"), reply[:80]
    assert "Model" in reply, "the notice must say where to go to fix it"


def test_an_unknown_provider_is_recorded_rather_than_silently_faked(caplog):
    """It still answers — refusing mid-chat is worse — but it leaves a trace."""
    import logging

    from lodestone.models.registry import get_provider
    with caplog.at_level(logging.WARNING):
        assert get_provider("not-a-provider").name == "mock"
    assert any("unknown provider" in r.message for r in caplog.records), caplog.text
