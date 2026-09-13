"""The `Connector` interface, frozen.

`REGISTRY` plus duck typing is a design that invites a new connector to declare
half the interface and look fine until the drawer renders it — the UI reads
`label`, `platforms` and `is_configured()` to decide what to show, and a missing
one surfaces as a blank card or a control that cannot work, not as an error.

Nothing here needs a fake: these are properties of the classes themselves.
"""
from __future__ import annotations

import inspect

import pytest

from lodestone.connectors import REGISTRY, Connector, SyncResult, get_connector

CLASSES = sorted(REGISTRY.items())
IDS = [name for name, _ in CLASSES]


@pytest.mark.parametrize("name,cls", CLASSES, ids=IDS)
def test_declares_its_identity(name, cls):
    assert cls.name == name, "the registry key and the class name must agree"
    assert cls.label and cls.label != Connector.label, (
        f"{name} never set a human-readable label — the UI would show 'Base'")


@pytest.mark.parametrize("name,cls", CLASSES, ids=IDS)
def test_reports_whether_it_can_run(name, cls):
    """`is_configured()` returns (ready, reason) and the reason must be useful.

    "Never show a control that cannot work" — the reason is the text the user
    reads in the place they are looking, so an empty one is a silent dead end.
    """
    ready, reason = cls().is_configured()
    assert isinstance(ready, bool)
    assert isinstance(reason, str)
    if not ready:
        assert reason.strip(), f"{name} refuses to run but will not say why"


@pytest.mark.parametrize("name,cls", CLASSES, ids=IDS)
def test_sync_is_implemented_and_keyword_only(name, cls):
    assert cls.sync is not Connector.sync, f"{name} never implemented sync()"
    params = list(inspect.signature(cls.sync).parameters.values())
    positional = [p for p in params[1:]
                  if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    assert not positional, (
        f"{name}.sync takes positional arguments {[p.name for p in positional]}; "
        "the scheduler calls every connector the same way, so options must be "
        "keyword-only")
    assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params), (
        f"{name}.sync must accept **kwargs — the scheduler passes options that "
        "not every connector understands")


@pytest.mark.parametrize("name,cls", CLASSES, ids=IDS)
def test_platform_gate_is_honest(name, cls):
    """A macOS-only connector must say so, rather than failing at sync time."""
    assert cls.platforms is None or isinstance(cls.platforms, tuple)
    assert isinstance(cls.supported_here(), bool)


@pytest.mark.parametrize("name,cls", CLASSES, ids=IDS)
def test_unconfigured_sync_fails_softly(name, cls):
    """A connector nobody has set up must return a SyncResult, never raise.

    The scheduler catches exceptions, but a raise loses the reason: the user is
    shown "sync failed" where they could have been shown "paste your token".
    """
    conn = cls()
    ready, _ = conn.is_configured()
    if ready:
        pytest.skip(f"{name} is configured in this environment")
    result = conn.sync(interactive=False)
    assert isinstance(result, SyncResult)
    assert result.errors, f"{name} was not configured yet reported no problem"


def test_registry_round_trips_every_name():
    for name in REGISTRY:
        assert isinstance(get_connector(name), Connector)


def test_unknown_connector_names_the_known_ones():
    """An error the developer can act on, not a bare KeyError."""
    with pytest.raises(KeyError) as exc:
        get_connector("definitely-not-a-connector")
    assert "known" in str(exc.value)
