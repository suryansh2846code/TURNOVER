"""Structural freeze for the model layer.

`test_model_system_freeze.py` locks *behaviour* (gating, binding, secrets).
This locks *structure*: a provider must be complete in every registry, its
default must be real, and the hygiene rules that this layer kept regressing on
must hold. Each assertion here corresponds to a bug that actually shipped.

Adding a provider should fail these until it is wired up everywhere.
"""
import ast
import re
from pathlib import Path

import pytest

from lodestone.models.auth_flows import ApiKeyOnlyFlow, AuthStart, AuthStatus, get_flow
from lodestone.models.capabilities import CAPABILITIES_REGISTRY, get_capabilities
from lodestone.models.discovery import normalize_provider_id
from lodestone.models.registry import (_LOCALITY, _REGISTRY, MODEL_CATALOG,
                                       PRIMARY_PROVIDERS)

MODELS_DIR = Path(__file__).parent.parent / "lodestone/models"

# Verified dead against the live providers on 2026-09-12. Re-verify before
# removing anything from this list; a retired id renders as selectable and then
# fails at send time, which is worse than a short catalog.
RETIRED_IDS = {
    "claude-fable-5-1", "claude-3-7-sonnet", "claude-3-7-sonnet-latest",
    "claude-3-5-sonnet", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest",
    "claude-3-opus-latest", "grok-3", "grok-3-mini", "grok-2-latest",
    "grok-2-vision-latest", "grok-2-1212", "grok-beta", "gemini-2.0-flash",
    "gemini-1.5-pro", "gemini-1.5-flash", "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.5-sonnet", "claude-3.7-sonnet", "claude-3.5-sonnet",
    "llama3.1", "gpt-4o", "gpt-4o-mini", "o1",
}


# ── every provider is complete everywhere ────────────────────────────────
@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_provider_is_registered_everywhere(pid):
    assert pid in _REGISTRY, f"{pid} has no provider class"
    assert pid in MODEL_CATALOG, f"{pid} has no catalog entry"
    assert pid in CAPABILITIES_REGISTRY, f"{pid} has no capabilities"
    assert pid in _LOCALITY, f"{pid} has no locality (where does its data go?)"


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_catalog_entry_is_well_formed(pid):
    entry = MODEL_CATALOG[pid]
    assert entry["id"] == pid and entry["label"]
    assert entry["models"], f"{pid} offers no models"
    for m in entry["models"]:
        assert m["id"] and m["name"], f"{pid} has a malformed model row: {m}"


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_default_model_is_offered(pid):
    entry = MODEL_CATALOG[pid]
    assert entry["default_model"] in {m["id"] for m in entry["models"]}, \
        f"{pid} defaults to a model it does not list"


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_provider_class_default_matches_the_catalog(pid):
    """These drifted silently — openrouter's class default was a retired id
    long after the catalog had been updated."""
    cls = _REGISTRY[pid]
    class_default = getattr(cls, "default_model", None) or getattr(cls, "model", None)
    if class_default:
        assert class_default == MODEL_CATALOG[pid]["default_model"], (
            f"{pid}: class default {class_default!r} != catalog "
            f"{MODEL_CATALOG[pid]['default_model']!r}")


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_no_retired_model_ids_are_offered(pid):
    ids = {m["id"] for m in MODEL_CATALOG[pid]["models"]}
    assert not (ids & RETIRED_IDS), f"{pid} lists retired ids: {sorted(ids & RETIRED_IDS)}"


def test_no_retired_id_is_offered_by_discovery():
    """Covers the `_fallback_*()` lists and the inline CLI/subscription lists.

    Scoped to models we *offer*: substring heuristics elsewhere (e.g. treating a
    `gpt-4o` a user's account still exposes as a vision model) are legitimate
    and must keep working.
    """
    src = (MODELS_DIR / "discovery.py").read_text()
    offered = set(re.findall(r'DiscoveredModel\(\s*"([^"]+)"', src))
    assert not (offered & RETIRED_IDS), \
        f"discovery offers retired ids: {sorted(offered & RETIRED_IDS)}"


def test_no_retired_id_is_used_as_a_ui_placeholder():
    """The model-name hints in the UI are copy users paste — they must be real."""
    src = (MODELS_DIR.parent / "web/app.js").read_text()
    hints = re.search(r"const MODEL_HINTS[^=]*=\s*\{(.*?)\};", src, re.S)
    if not hints:
        return
    named = set(re.findall(r"[\s,\"]([a-z0-9][a-z0-9.\-/]{3,})", hints.group(1)))
    assert not (named & RETIRED_IDS), f"UI hints name retired ids: {sorted(named & RETIRED_IDS)}"


# ── aliases ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("alias,canonical", [
    ("anthropic", "claude"), ("google", "gemini"), ("grok", "xai"),
])
def test_aliases_resolve_and_remain_constructible(alias, canonical):
    assert normalize_provider_id(alias) == canonical
    assert alias in _REGISTRY, f"{alias} must stay constructible for old configs"
    assert get_capabilities(alias) is get_capabilities(canonical)


# ── sign-in flows ────────────────────────────────────────────────────────
@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_every_provider_resolves_to_a_working_flow(pid):
    flow = get_flow(pid)
    assert isinstance(flow.start(), AuthStart)
    assert isinstance(flow.status(), AuthStatus)


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_key_only_providers_get_the_key_only_flow(pid):
    caps = get_capabilities(pid)
    if caps and caps.api_key_only:
        assert isinstance(get_flow(pid), ApiKeyOnlyFlow)
        assert not caps.has_interactive_signin


def test_no_provider_falls_back_to_a_generic_browser_flow_by_accident():
    """BrowserFlow just opens a URL — acceptable only where there is genuinely
    nothing to sign into."""
    from lodestone.models.auth_flows import BrowserFlow

    generic = [p for p in PRIMARY_PROVIDERS if isinstance(get_flow(p), BrowserFlow)]
    assert set(generic) <= {"ollama", "mock"}, \
        f"these silently fell back to BrowserFlow: {generic}"


# ── hygiene the layer kept regressing on ─────────────────────────────────
def _unused_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    imported = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported[(a.asname or a.name).split(".")[0]] = True
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    imported[a.asname or a.name] = True
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            v = n
            while isinstance(v, ast.Attribute):
                v = v.value
            if isinstance(v, ast.Name):
                used.add(v.id)
    return sorted(k for k in imported if k not in used and k != "annotations")


@pytest.mark.parametrize("path", sorted(MODELS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_unused_imports(path):
    if path.name == "__init__.py":      # deliberate re-exports, guarded by __all__
        return
    assert not _unused_imports(path), f"{path.name}: unused imports"


def test_no_competitor_paths_are_read():
    """Model discovery and credentials must never come from another product."""
    for f in MODELS_DIR.glob("*.py"):
        src = f.read_text()
        assert "Application Support/Turnstone" not in src, f"{f.name} reads Turnstone's files"


def test_provider_count_is_deliberate():
    """A canary: adding a provider should be a decision, and should fail the
    completeness tests above until it is wired up everywhere."""
    assert len(PRIMARY_PROVIDERS) == 11, (
        f"provider count changed to {len(PRIMARY_PROVIDERS)} — make sure the new "
        "provider is in _REGISTRY, MODEL_CATALOG, CAPABILITIES_REGISTRY, _LOCALITY, "
        "COMPOSER_PROVIDERS and has an auth flow")


@pytest.mark.parametrize("pid", PRIMARY_PROVIDERS)
def test_key_only_providers_report_no_account_credential(pid):
    """xAI is the case that matters: its OAuth token authenticates but grants no
    api.x.ai credits, so counting it as a connected account would unlock models
    that fail on the first message. Credential stores (the Keychain) are not
    scoped by LODESTONE_HOME, so this must hold regardless of local state."""
    from lodestone.models.entitlements import provider_credentials

    caps = get_capabilities(pid)
    if caps and caps.api_key_only:
        creds = provider_credentials(pid)
        assert creds["account"]["supported"] is False, f"{pid} claims account support"
        assert creds["account"]["connected"] is False


def test_a_fresh_install_connects_nothing_remote():
    """Detection is not consent — on first launch every cloud provider must be
    disconnected with all models locked."""
    from lodestone.models.registry import get_model_catalog

    for entry in get_model_catalog():
        if entry["locality"] == "local" or entry["id"] == "mock":
            continue
        if entry["connected"]:
            pytest.skip(f"{entry['id']} is genuinely connected in this environment")
        assert all(m["locked"] for m in entry["models"]), \
            f"{entry['id']} is disconnected but has unlocked models"
