"""A stored model id is a request, not a guarantee — at every entry point.

Reported from the running app: a ChatGPT **Free** account, whose plan offers
`gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini`, was answered with

    🔒 Model `gpt-5.6-terra` is not supported on your ChatGPT Free plan

`resolve_usable_model()` exists to prevent exactly this, and `run_turn` called
it — but a model id reaches a provider from several places, and the others
built one straight from storage:

    provider = get_provider(p_name, m_name)   # routes/agents.py  (welcome)
    provider = get_provider(p_name, m_name)   # routes/brain.py   (digest)

Those two are the lead agent's first message and the onboarding digest: the
first two screens a new user sees. So the repair moved into `get_provider`,
where *every* caller passes, rather than staying a thing each route has to
remember.
"""
from __future__ import annotations

import pytest

from lodestone.models import registry

#: What a ChatGPT Free account reports it can run.
FREE_ACCOUNT = [
    {"id": "gpt-5.6-terra", "locked": True, "plan_required": "Pro"},
    {"id": "gpt-5.6-luna", "locked": True, "plan_required": "Pro"},
    {"id": "gpt-5.5", "locked": False},
    {"id": "gpt-5.4", "locked": False},
    {"id": "gpt-5.4-mini", "locked": False},
]
UNLOCKED = {m["id"] for m in FREE_ACCOUNT if not m["locked"]}


@pytest.fixture
def account(monkeypatch):
    """Install a discovered catalog, and stop provider instances being reused
    across cases — `get_provider` is lru_cached on (name, model)."""
    def install(models):
        registry.get_provider.cache_clear()
        monkeypatch.setattr("lodestone.models.discovery.get_discovered_models",
                            lambda *a, **k: (models, {}))
    yield install
    registry.get_provider.cache_clear()


def test_a_locked_stored_id_never_reaches_the_provider(account):
    account(FREE_ACCOUNT)

    provider = registry.get_provider("openai", "gpt-5.6-terra")

    assert provider.model in UNLOCKED, (
        f"built a provider bound to {provider.model!r}; the account cannot run "
        "it, so the user's next message fails with a plan error about a model "
        "they may never have chosen"
    )


def test_auto_builds_a_provider_the_account_can_run(account):
    """No model means Auto, which must not mean the hardcoded default."""
    account(FREE_ACCOUNT)

    assert registry.get_provider("openai", None).model in UNLOCKED


def test_a_model_the_account_offers_is_left_alone(account):
    account(FREE_ACCOUNT)

    assert registry.get_provider("openai", "gpt-5.4").model == "gpt-5.4"


def test_a_discovery_failure_honours_the_request(account, monkeypatch):
    """Never block a turn on our own probe failing."""
    registry.get_provider.cache_clear()

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("lodestone.models.discovery.get_discovered_models", boom)

    assert registry.get_provider("openai", "gpt-5.5").model == "gpt-5.5"


def test_a_fallback_catalog_is_not_evidence_about_this_account(account):
    """A hardcoded list proves nothing — substituting from one would swap out a
    model the user can legitimately run."""
    account([{"id": "gpt-5.5", "locked": False, "is_fallback": True}])

    assert registry.get_provider("openai", "gpt-5.6-terra").model == "gpt-5.6-terra"


def test_routes_reach_a_provider_only_through_the_seam():
    """The re-check only holds while `get_provider` is the only door.

    A route that instantiates a provider class itself — `OpenAICompatProvider(
    model=saved_id)` — bypasses it and gets the old bug back. The two bypasses
    that caused this were plain, correct-looking lines, and nothing failed when
    they were written, so the guard is a source check on purpose.
    """
    import pathlib
    import re

    import lodestone
    from lodestone.models.registry import _REGISTRY

    classes = {cls.__name__ for cls in _REGISTRY.values()}
    direct = re.compile(rf"\b({'|'.join(sorted(classes))})\s*\(")

    offenders = []
    for path in (pathlib.Path(lodestone.__file__).parent / "api" / "routes").glob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if direct.search(line) and "import" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "these build a provider directly, so a stored model id is never "
        f"re-checked against what the account can run: {offenders}"
    )
