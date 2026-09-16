""""Auto" must mean a model this account can run.

Reported from the running app: a ChatGPT **Free** account was told

    🔒 Model `gpt-5.6-terra` is not supported on your ChatGPT Free plan
       (requires Pro). Available models on your plan: gpt-5.4, gpt-5.4-mini,
       gpt-5.5.

about a model the user had never selected. They had chosen a provider, which
leaves the model on "Auto".

`resolve_usable_model()` re-checks a *requested* id against what the account
offers, and it short-circuited on a falsy one: no model meant nothing to check,
so it returned None and deferred to `registry.default_model` — `gpt-5.6-terra`,
a hardcoded id chosen long before this user had an account. The one setting that
is supposed to be the safe choice was the only one that reached a locked model.

The repair path itself worked fine; the request never got there.
"""
from __future__ import annotations

import pytest

from chitragupta.models import entitlements

#: The reported account: the strong models present and marked locked, because a
#: user must still see what a plan would buy them.
FREE_ACCOUNT = [
    {"id": "gpt-5.6-terra", "locked": True},
    {"id": "gpt-5.6-luna", "locked": True},
    {"id": "gpt-5.5", "locked": False},
    {"id": "gpt-5.4", "locked": False},
    {"id": "gpt-5.4-mini", "locked": False},
]
LOCKED = {m["id"] for m in FREE_ACCOUNT if m["locked"]}


@pytest.fixture
def account(monkeypatch):
    def install(models):
        monkeypatch.setattr("chitragupta.models.discovery.get_discovered_models",
                            lambda *a, **k: (models, {}))
    return install


def test_auto_resolves_to_a_model_the_account_can_run(account):
    """The reported bug, exactly.

    Asserting only "not locked" would pass on the bug: it returned `None`, and
    None is not a locked id — it is the *deferral* that reached the hardcoded
    default. What has to be true is that a real, runnable id comes back.
    """
    account(FREE_ACCOUNT)

    usable, _ = entitlements.resolve_usable_model("openai", None)

    unlocked = {m["id"] for m in FREE_ACCOUNT if not m["locked"]}
    assert usable in unlocked, (
        f"'Auto' resolved to {usable!r}. None means "
        "`registry.default_model` decides, which is how a Free account was "
        "refused for a model it never picked")


def test_auto_picks_the_best_model_the_account_offers(account):
    account(FREE_ACCOUNT)

    usable, _ = entitlements.resolve_usable_model("openai", None)

    assert usable == "gpt-5.5"


def test_auto_is_not_reported_as_a_substitution(account):
    """Nothing was replaced — the user asked for "whatever works", and got it.
    Reporting a substitution here would make the UI repair a saved binding that
    was never wrong."""
    account(FREE_ACCOUNT)

    _, replaced = entitlements.resolve_usable_model("openai", None)

    assert replaced is None


def test_a_locked_explicit_choice_is_still_substituted(account):
    account(FREE_ACCOUNT)

    usable, replaced = entitlements.resolve_usable_model("openai", "gpt-5.6-terra")

    assert replaced == "gpt-5.6-terra"
    assert usable not in LOCKED


def test_an_account_that_offers_everything_gets_the_best(account):
    """The mirror case a careless fix breaks: a paid plan must not be demoted."""
    account([{"id": m["id"], "locked": False} for m in FREE_ACCOUNT])

    usable, _ = entitlements.resolve_usable_model("openai", None)

    assert usable == "gpt-5.6-terra"


# ── when we cannot tell, we must not guess ────────────────────────────────


def test_a_fallback_catalog_leaves_the_default_alone(account):
    """A hardcoded list is not evidence about this account. Choosing from one
    would override a model the user can legitimately run."""
    account([{"id": "gpt-5.5", "locked": False, "is_fallback": True}])

    usable, _ = entitlements.resolve_usable_model("openai", None)

    assert usable is None


def test_a_discovery_failure_leaves_the_default_alone(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("chitragupta.models.discovery.get_discovered_models", boom)

    usable, _ = entitlements.resolve_usable_model("openai", None)

    assert usable is None


def test_an_account_with_nothing_unlocked_leaves_the_default_alone(account):
    account([{"id": "gpt-5.6-terra", "locked": True}])

    usable, _ = entitlements.resolve_usable_model("openai", None)

    assert usable is None


# ── the message that came with it ─────────────────────────────────────────


def test_the_refusal_does_not_invent_a_required_plan():
    """It read "(requires Pro)" whenever the entitlement tables had no opinion,
    which is a specific, confident claim nobody had checked. We know it is not
    on this plan; we do not know which plan would have it."""
    source = (__import__("pathlib").Path(entitlements.__file__).parent
              / "chatgpt_auth.py").read_text()

    assert 'plan_req or "Pro"' not in source
