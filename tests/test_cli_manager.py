"""Lodestone installs the vendor CLIs itself.

Claude, Cursor and Grok reach a paid plan only through their own CLI. Telling a
user to open a terminal and paste a curl command is a developer tool, not a
product — so these are fetched, pinned and managed for them.

Artifacts are downloaded directly; a vendor's install script is read as a
manifest, never executed.
"""
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from lodestone.models import cli_manager
from lodestone.models.cli_manager import (PROVIDER_CLI, SPECS, install_cli,
                                          install_status, installed_version,
                                          managed_bin_dir, managed_binary,
                                          uninstall_cli)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_manager, "get_settings", lambda: type("S", (), {"home": tmp_path})())
    return tmp_path


def _targz(names: dict[str, bytes]) -> bytes:
    """A vendor-shaped archive: everything nested one level down."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in names.items():
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_download(payload: bytes):
    def _dl(url, dest, on_progress):
        dest.write_bytes(payload)
        on_progress(len(payload), len(payload))
    return _dl


# ── the provider -> CLI map ──────────────────────────────────────────────
@pytest.mark.parametrize("provider,vendor", [
    ("cursor", "cursor"), ("xai", "grok"), ("grok", "grok"),
])
def test_providers_map_to_their_vendor_cli(provider, vendor):
    assert PROVIDER_CLI[provider] == vendor
    assert vendor in SPECS


def test_providers_without_a_managed_cli_say_so():
    assert "openai" not in PROVIDER_CLI
    assert "gemini" not in PROVIDER_CLI


# ── installing ───────────────────────────────────────────────────────────
def test_installs_a_raw_binary_and_links_it(home):
    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.30", "https://x.ai/cli/grok-1.0.30", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"#!/bin/sh\nexit 0\n")), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "grok 1.0.30"
        path = install_cli("grok")

    assert path.exists()
    assert installed_version("grok") == "1.0.30"
    link = managed_bin_dir() / "grok"
    assert link.is_symlink() and Path(link.resolve()) == path


def test_installs_a_tarball_and_normalises_the_binary_name(home):
    """Cursor ships `cursor-agent` inside a nested directory; we expose `agent`."""
    archive = _targz({"cursor-agent": b"#!/bin/sh\nexit 0\n", "README": b"x"})
    with patch.object(cli_manager, "latest_release",
                      return_value=("2026.09.10", "https://downloads.cursor.com/x.tar.gz", "targz")), \
         patch.object(cli_manager, "_download", _fake_download(archive)), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "2026.09.10"
        path = install_cli("cursor")

    assert path.name == "agent" and path.exists()
    # both names the vendor might be invoked by are linked
    for name in ("agent", "cursor-agent"):
        assert (managed_bin_dir() / name).is_symlink()


def test_installed_binary_is_executable(home):
    import os

    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"x")), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        path = install_cli("grok")
    assert os.access(path, os.X_OK)


def test_a_binary_that_does_not_run_is_rejected(home):
    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"garbage")), \
         patch("subprocess.run", side_effect=OSError("Exec format error")):
        with pytest.raises(RuntimeError, match="failed to verify"):
            install_cli("grok")
    assert managed_binary("grok") is None, "a broken download must not be linked"


def test_reinstalling_the_same_version_is_a_relink_not_a_download(home):
    calls = {"n": 0}

    def counting(url, dest, on_progress):
        calls["n"] += 1
        dest.write_bytes(b"x")
        on_progress(1, 1)

    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", counting), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        install_cli("grok")
        install_cli("grok")
    assert calls["n"] == 1, "re-downloaded an already-installed version"


def test_uninstall_removes_only_our_copy(home):
    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"x")), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        install_cli("grok")

    assert uninstall_cli("grok") is True
    assert managed_binary("grok") is None
    assert installed_version("grok") is None


# ── status reporting ─────────────────────────────────────────────────────
def test_status_before_and_after_install(home):
    before = install_status("grok")
    assert before["installable"] is True and before["installed"] is False

    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"x")), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        install_cli("grok")

    after = install_status("grok")
    assert after["installed"] is True and after["version"] == "1.0.0"
    assert after["path"] and after["percent"] == 100


def test_progress_is_reported_monotonically(home):
    seen = []
    with patch.object(cli_manager, "latest_release",
                      return_value=("1.0.0", "https://x", "binary")), \
         patch.object(cli_manager, "_download", _fake_download(b"x" * 1000)), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        install_cli("grok", lambda msg, pct: seen.append(pct))
    assert seen and seen[-1] == 100
    assert seen == sorted(seen), f"progress went backwards: {seen}"


# ── we never execute a vendor's installer ────────────────────────────────
def test_installers_are_read_as_manifests_never_executed():
    """Piping a vendor script into a shell would run arbitrary code as the user
    and could not be redirected into our own directory."""
    src = (Path(__file__).parent.parent / "lodestone/models/cli_manager.py").read_text()
    assert "shell=True" not in src
    assert "| bash" not in src and "|bash" not in src
    assert "install.sh" in src or "cursor.com/install" in src  # read, not run


def test_resolvers_produce_a_plausible_artifact_url():
    """Offline check of the URL shape; the live probe lives in the docs."""
    with patch("httpx.get") as get:
        get.return_value.text = "1.0.30"
        version, url, kind = cli_manager._resolve_grok()
    assert version == "1.0.30" and kind == "binary"
    assert url.startswith("https://x.ai/cli/grok-1.0.30-")

    with patch("httpx.get") as get:
        get.return_value.text = 'DOWNLOAD_URL="https://downloads.cursor.com/lab/2026.09.10-abc/${OS}/..."'
        version, url, kind = cli_manager._resolve_cursor()
    assert version == "2026.09.10-abc" and kind == "targz"
    assert url.endswith("agent-cli-package.tar.gz")


def test_a_malformed_version_is_rejected():
    with patch("httpx.get") as get:
        get.return_value.text = "; rm -rf /"
        with pytest.raises(RuntimeError, match="unexpected Grok version"):
            cli_manager._resolve_grok()
