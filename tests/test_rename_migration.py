"""The rename must not cost the user their brain.

The app was Lodestone until 2026-09-16. A user's data was keyed to that name in
four places: `~/Library/Lodestone`, a Keychain service called `Lodestone`,
`LODESTONE_*` environment variables, and `lodestone_*` in the browser. Renaming
without carrying those across opens the app on an empty brain with nothing
connected and no explanation — the failure `/CLAUDE.md` puts first:

    Never lose the user's state to our mistakes.

The rename was ours, so the migration is ours. These pin the three server-side
mechanisms; the browser half is covered in `tests/js/` via `core.js`.
"""
from __future__ import annotations

import pytest

from chitragupta import migration


# ── the home directory ──────────────────────────────────────────────────────
def test_a_pre_rename_brain_is_carried_across(tmp_path, monkeypatch):
    old = tmp_path / "Library" / "Lodestone"
    (old / "logs").mkdir(parents=True)
    (old / "chitragupta.db").write_text("the whole brain")
    monkeypatch.setattr(migration, "legacy_home", lambda: old)

    new = tmp_path / "Library" / "Chitragupta"
    assert migration.migrate_home(new) is True

    assert (new / "chitragupta.db").read_text() == "the whole brain", (
        "the user's brain did not survive the rename")
    assert (new / "logs").is_dir()
    assert not old.exists(), "the old home was left behind as a duplicate"


def test_a_fresh_install_has_nothing_to_move(tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "legacy_home", lambda: tmp_path / "absent")
    assert migration.migrate_home(tmp_path / "new") is False


def test_an_empty_new_home_is_not_treated_as_a_real_one(tmp_path, monkeypatch):
    """`ensure_home()` may have created the directory before we ran. An empty
    directory is not a second brain and must not block the move."""
    old = tmp_path / "Lodestone"
    old.mkdir()
    (old / "chitragupta.db").write_text("data")
    monkeypatch.setattr(migration, "legacy_home", lambda: old)

    new = tmp_path / "Chitragupta"
    new.mkdir()                                  # exists, but empty

    assert migration.migrate_home(new) is True
    assert (new / "chitragupta.db").read_text() == "data"


def test_two_real_brains_are_never_merged(tmp_path, monkeypatch):
    """The user has already run the new version. Silently overwriting the newer
    brain with the older one is the one outcome worse than doing nothing."""
    old = tmp_path / "Lodestone"
    old.mkdir()
    (old / "chitragupta.db").write_text("old")
    monkeypatch.setattr(migration, "legacy_home", lambda: old)

    new = tmp_path / "Chitragupta"
    new.mkdir()
    (new / "chitragupta.db").write_text("new")

    assert migration.migrate_home(new) is False
    assert (new / "chitragupta.db").read_text() == "new", "the newer brain was clobbered"
    assert (old / "chitragupta.db").read_text() == "old", "the older brain was destroyed"


def test_a_failed_move_is_not_a_failed_launch(tmp_path, monkeypatch):
    """A migration that raises must not stop the app from opening."""
    old = tmp_path / "Lodestone"
    old.mkdir()
    (old / "x").write_text("x")
    monkeypatch.setattr(migration, "legacy_home", lambda: old)

    def _boom(*_a, **_k):
        raise OSError("cross-device link")

    monkeypatch.setattr(type(old), "rename", _boom)
    assert migration.migrate_home(tmp_path / "Chitragupta") is False   # no raise


# ── environment variables ───────────────────────────────────────────────────
def test_the_old_env_var_still_works(monkeypatch):
    """It is in somebody's shell profile and we do not edit those."""
    monkeypatch.setenv("LODESTONE_HOME", "/tmp/somewhere")
    assert migration.legacy_env("CHITRAGUPTA_HOME") == "/tmp/somewhere"


def test_an_unset_old_var_is_simply_absent(monkeypatch):
    monkeypatch.delenv("LODESTONE_HOME", raising=False)
    assert migration.legacy_env("CHITRAGUPTA_HOME") is None


def test_only_our_own_prefix_is_translated():
    assert migration.legacy_env("PATH") is None
    assert migration.legacy_env("OPENAI_API_KEY") is None


# ── Keychain secrets ────────────────────────────────────────────────────────
def test_a_secret_found_under_the_old_service_is_rehomed():
    written: dict[str, str] = {}
    deleted: list[str] = []

    value = migration.migrate_secret(
        "NOTION_TOKEN",
        read_legacy=lambda k: "ntn_secret" if k == "NOTION_TOKEN" else None,
        write_new=lambda k, v: written.update({k: v}) or True,
        delete_legacy=deleted.append,
    )

    assert value == "ntn_secret", "the caller did not get the credential"
    assert written == {"NOTION_TOKEN": "ntn_secret"}, "it was not re-homed"
    assert deleted == ["NOTION_TOKEN"], "the old copy was left behind"


def test_a_secret_that_was_never_there_moves_nothing():
    written: dict[str, str] = {}
    out = migration.migrate_secret(
        "ABSENT", read_legacy=lambda k: None,
        write_new=lambda k, v: written.update({k: v}) or True,
        delete_legacy=lambda k: None)
    assert out is None and written == {}


def test_a_credential_is_never_dropped_just_because_the_move_failed():
    """The user gets a working app now; the next launch tries again. Losing the
    credential to a tidy-up step is far worse than migrating it twice."""
    deleted: list[str] = []

    def _write_fails(_k, _v):
        raise OSError("keychain is locked")

    value = migration.migrate_secret(
        "OPENAI_API_KEY", read_legacy=lambda k: "sk-live",
        write_new=_write_fails, delete_legacy=deleted.append)

    assert value == "sk-live", "the secret was lost because re-homing failed"
    assert deleted == [], "the only remaining copy was deleted"


# ── the seam into config ────────────────────────────────────────────────────
def test_config_reads_the_old_keychain_service_before_giving_up(monkeypatch):
    """End to end through `Settings`: nothing under the new service, something
    under the old one, and the caller is none the wiser."""
    from chitragupta.config import Settings, forget_cached_secrets

    forget_cached_secrets()
    s = Settings()
    monkeypatch.setattr(Settings, "_keychain_ok", lambda self: True)
    monkeypatch.setattr(Settings, "_load_secrets", lambda self: {})
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    seen: list[tuple[str, str]] = []

    def _read(_self, service, key):
        seen.append((service, key))
        return "from-the-old-service" if service == "Lodestone" else None

    monkeypatch.setattr(Settings, "_kc_read", _read)
    monkeypatch.setattr(Settings, "_kc_set", lambda self, k, v: True)
    monkeypatch.setattr(Settings, "_kc_delete", lambda self, k, service=None: None)

    assert s.get_secret("NOTION_TOKEN") == "from-the-old-service"
    assert [svc for svc, _ in seen] == ["Chitragupta", "Lodestone"], (
        f"wrong lookup order: {seen}")
    forget_cached_secrets()


@pytest.mark.parametrize("name", ["LEGACY_KEYCHAIN_SERVICE", "LEGACY_ENV_PREFIX"])
def test_the_old_names_stay_greppable(name):
    """When this module is finally deleted, these are what the sweep looks for."""
    assert "odestone" in getattr(migration, name).lower() or \
           "LODESTONE" in getattr(migration, name)


# ── the two bugs this migration actually caused ─────────────────────────────
def test_a_chosen_home_never_absorbs_the_legacy_brain(tmp_path, monkeypatch):
    """The expensive one.

    `conftest.py` points CHITRAGUPTA_HOME at a fresh `mkdtemp()`. An empty
    directory looked exactly like "the new home does not exist yet", so the
    first test run after the rename moved a real 745 MB brain out of
    ~/Library and into a pytest temp directory — where the next `pytest` run
    would have been within its rights to write all over it.

    A home somebody named is a home somebody meant.
    """
    monkeypatch.setenv("CHITRAGUPTA_HOME", str(tmp_path / "chosen"))
    assert migration.home_is_explicit() is True

    monkeypatch.delenv("CHITRAGUPTA_HOME", raising=False)
    monkeypatch.setenv("LODESTONE_HOME", str(tmp_path / "chosen"))
    assert migration.home_is_explicit() is True, (
        "the pre-rename variable also names a home deliberately")

    monkeypatch.delenv("LODESTONE_HOME", raising=False)
    assert migration.home_is_explicit() is False


def test_get_settings_does_not_migrate_into_an_explicit_home(tmp_path, monkeypatch):
    """End to end: the guard is wired, not merely available."""
    from chitragupta.config import get_settings

    real = tmp_path / "Library" / "Lodestone"
    real.mkdir(parents=True)
    (real / "lodestone.db").write_text("the user's actual brain")
    monkeypatch.setattr(migration, "legacy_home", lambda: real)

    chosen = tmp_path / "chosen"
    monkeypatch.setenv("CHITRAGUPTA_HOME", str(chosen))
    get_settings.cache_clear()
    get_settings()

    assert (real / "lodestone.db").exists(), (
        "a deliberately-chosen home swallowed the user's real brain")
    get_settings.cache_clear()


def test_the_database_files_are_renamed_too(tmp_path):
    """Moving the directory is not enough.

    `settings.db_path` names `chitragupta.db`. A home full of `lodestone.db`
    therefore opens as a brand-new empty brain sitting next to 33 MB of the
    user's real memories — which looks, from the outside, exactly like the data
    loss this whole module exists to prevent.
    """
    home = tmp_path / "Chitragupta"
    home.mkdir()
    (home / "lodestone.db").write_text("33MB of memories, pretend")
    (home / "lodestone.db-wal").write_text("uncheckpointed pages")
    (home / "lodestone.db-shm").write_text("shared memory index")
    (home / "brain.db").write_text("untouched")

    renamed = migration.migrate_data_files(home)

    assert (home / "chitragupta.db").read_text() == "33MB of memories, pretend"
    assert (home / "chitragupta.db-wal").exists(), (
        "the write-ahead log was stranded — committed pages SQLite will never "
        "look at again")
    assert (home / "chitragupta.db-shm").exists()
    assert not (home / "lodestone.db").exists()
    assert (home / "brain.db").read_text() == "untouched", "unrelated file touched"
    assert len(renamed) == 3


def test_renaming_data_files_never_clobbers_a_newer_database(tmp_path):
    home = tmp_path / "Chitragupta"
    home.mkdir()
    (home / "lodestone.db").write_text("old")
    (home / "chitragupta.db").write_text("new")

    migration.migrate_data_files(home)

    assert (home / "chitragupta.db").read_text() == "new"
    assert (home / "lodestone.db").read_text() == "old", "the old copy was destroyed"


def test_renaming_data_files_is_idempotent(tmp_path):
    home = tmp_path / "Chitragupta"
    home.mkdir()
    (home / "lodestone.db").write_text("x")
    assert len(migration.migrate_data_files(home)) == 1
    assert migration.migrate_data_files(home) == []
