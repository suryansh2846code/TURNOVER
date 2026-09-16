"""Carrying a user across the rename from Lodestone to Chitragupta.

The app was called Lodestone until 2026-09-16. Everything a user owns was keyed
to that name — a brain in `~/Library/Lodestone`, secrets in a Keychain service
called `Lodestone`, settings under `LODESTONE_*`, browser prefs under
`lodestone_*`. A rename that ignored any of those would open on an empty brain
with no accounts connected and no explanation, which is precisely the failure
`/CLAUDE.md` puts first:

> **Never lose the user's state to our mistakes.**

The rename is ours. The migration is therefore ours too.

Three different mechanisms, because the three stores fail differently:

* **The home directory moves eagerly**, once, at startup. It is a `rename(2)` on
  the same volume, so 745 MB costs the same as 745 bytes — there is no progress
  bar to justify and nothing to stream.
* **Keychain secrets move lazily, on read.** We cannot enumerate our own items
  without walking the user's whole keychain, and we should not: the set of keys
  is open-ended (one per provider, per connector, per MCP server). So a miss
  under the new service falls back to the old one, and a hit is rewritten under
  the new name and removed from the old. After a few launches the old service is
  empty on its own, and nothing ever had to know the full list.
* **Environment variables are read, never moved.** `LODESTONE_HOME` is in
  somebody's shell profile and we do not edit those. It keeps working as a
  fallback, for good.

Browser `localStorage` is the fourth store; it migrates in `web/core.js`, because
only the page can reach it.
"""
from __future__ import annotations

import os
from pathlib import Path

from .log import get_logger, suppressed

log = get_logger(__name__)

#: What the app used to be called. Kept in one place so the sweep that finally
#: deletes this module has something to grep for.
LEGACY_NAME = "Lodestone"
LEGACY_ENV_PREFIX = "LODESTONE_"
LEGACY_KEYCHAIN_SERVICE = "Lodestone"


def home_is_explicit() -> bool:
    """Did something *choose* this home, rather than defaulting to it?

    Load-bearing, and bought the hard way. `migrate_home` used to run against
    whatever home was configured — and `tests/conftest.py` sets
    `CHITRAGUPTA_HOME` to a fresh `mkdtemp()`, which is empty. An empty target
    looked exactly like "the new home does not exist yet", so the first test run
    after the rename moved a real 745 MB brain out of `~/Library` and into a
    pytest temp directory.

    A home somebody named is a home somebody meant. Legacy data is never dragged
    into it.
    """
    return bool(os.environ.get("CHITRAGUPTA_HOME")
                or os.environ.get(LEGACY_ENV_PREFIX + "HOME"))


#: Files inside the home whose *names* carried the old brand. The directory
#: moving is not enough: `settings.db_path` now points at `chitragupta.db`, so a
#: migrated home full of `lodestone.db` opens as a brand-new empty brain sitting
#: next to 33 MB of the user's actual memories.
LEGACY_FILES = ("lodestone.db", "lodestone.db-wal", "lodestone.db-shm")


def migrate_data_files(home: Path) -> list[str]:
    """Rename the old brand's files inside an already-migrated home.

    Returns what it renamed. Separate from `migrate_home` because it also has to
    run for somebody whose home was *already* at the new path — a user who set
    `CHITRAGUPTA_HOME` by hand, or whose directory moved on an earlier launch
    that predated this function.

    The SQLite sidecars travel with the database. Renaming `foo.db` and leaving
    `foo.db-wal` behind strands any committed-but-uncheckpointed pages in a file
    SQLite will never look at again.
    """
    renamed: list[str] = []
    if not home.is_dir():
        return renamed
    for old_name in LEGACY_FILES:
        old = home / old_name
        new = home / old_name.replace("lodestone", "chitragupta", 1)
        if not old.exists() or new.exists():
            continue
        with suppressed("renaming a pre-rename database file"):
            old.rename(new)
            renamed.append(f"{old_name} -> {new.name}")
    if renamed:
        log.info("renamed pre-rename data files: %s", ", ".join(renamed))
    return renamed


def legacy_home() -> Path:
    """Where a pre-rename install kept its brain."""
    if os.name == "posix" and Path.home().joinpath("Library").exists():
        return Path.home() / "Library" / LEGACY_NAME
    return Path.home() / ".lodestone"


def legacy_env(name: str) -> str | None:
    """The `LODESTONE_`-prefixed twin of a `CHITRAGUPTA_` variable, if set.

    Read-only and permanent. A user who put `LODESTONE_HOME` in their shell
    profile years ago should not discover the rename by having the app quietly
    ignore it.
    """
    if not name.startswith("CHITRAGUPTA_"):
        return None
    return os.environ.get(LEGACY_ENV_PREFIX + name[len("CHITRAGUPTA_"):])


def migrate_home(new_home: Path) -> bool:
    """Move a pre-rename brain to the new location. Returns True if it moved.

    Deliberately conservative in every ambiguous case:

    * new home already exists and is non-empty → do nothing. Two brains means
      the user has already run the new version; silently merging them, or
      worse overwriting the newer with the older, is not a call to make
      automatically.
    * legacy home missing → nothing to do, which is every fresh install.
    * the move fails → log and carry on with an empty new home. A failed
      migration must not be a failed launch.
    """
    old = legacy_home()
    if not old.is_dir():
        return False
    if old.resolve() == new_home.resolve():
        return False
    if new_home.exists() and any(new_home.iterdir()):
        log.warning(
            "both %s and %s exist; keeping the new one and leaving the old "
            "in place untouched", old, new_home)
        return False

    # A static label: `tests/test_failures_are_recorded.py` requires one, and
    # it is right to — the paths are already in the exception the log records.
    with suppressed("moving the pre-rename data directory"):
        new_home.parent.mkdir(parents=True, exist_ok=True)
        if new_home.exists():
            new_home.rmdir()            # empty — `ensure_home` may have made it
        old.rename(new_home)
        log.info("moved your data from %s to %s", old, new_home)
        return True
    return False


def migrate_secret(key: str, read_legacy, write_new, delete_legacy) -> str | None:
    """Fetch one secret from the old Keychain service and re-home it.

    Called only when the new service missed. The callbacks are passed in rather
    than imported so this stays testable without a real Keychain — and so that
    `config.py` keeps sole ownership of how a secret is actually stored.

    A write that fails still returns the value: the user gets a working app now,
    and the next launch tries the move again. Losing the credential to a tidy-up
    step would be a far worse trade than migrating it twice.
    """
    value = read_legacy(key)
    if not value:
        return None
    moved = False
    with suppressed("re-homing a stored secret under the new Keychain service"):
        moved = bool(write_new(key, value))
    if moved:
        with suppressed("removing the pre-rename copy of a stored secret"):
            delete_legacy(key)
    return value
