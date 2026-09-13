"""Install and pin the vendor CLIs that back subscription sign-in.

Claude, Cursor and Grok all reach a paid plan through their own CLI — the CLI
owns the OAuth client, so `X login` is the only way to that consent screen.
Requiring users to install those by hand is the difference between a product
and a developer tool, so Lodestone fetches and manages them itself:

    ~/Library/Lodestone/agent-binaries/<vendor>/<version>/   the payload
    ~/Library/Lodestone/bin/<name>                           a stable symlink

**Artifacts are downloaded directly — we never pipe a vendor's installer into a
shell.** Each vendor's install script is read only as a manifest (it names a
version and a plain artifact URL); we then fetch that artifact ourselves. That
keeps the install auditable, lets it land in our own directory, and means a
compromised script cannot run arbitrary code as the user.

Installs run as a background job so the UI can show progress and a refresh
cannot kill one mid-download.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

_TIMEOUT = 120.0


@dataclass(frozen=True)
class CliSpec:
    vendor: str
    display: str
    binary: str                 # executable name we expose on disk
    aliases: tuple[str, ...]    # extra symlink names the vendor expects
    docs_url: str


SPECS: dict[str, CliSpec] = {
    "cursor": CliSpec("cursor", "Cursor CLI", "agent", ("cursor-agent",),
                      "https://cursor.com/docs/cli/overview"),
    "grok": CliSpec("grok", "Grok CLI", "grok", (),
                    "https://x.ai/news/grok-build-cli"),
}

# Which provider is served by which CLI.
PROVIDER_CLI = {"cursor": "cursor", "xai": "grok", "grok": "grok"}


def managed_root() -> Path:
    return get_settings().home / "agent-binaries"


def managed_bin_dir() -> Path:
    return get_settings().home / "bin"


def agent_workspace() -> Path:
    """An empty directory the agent CLIs run in.

    These are coding agents: in print mode they have file and shell tools. We
    only want text back, so they run here rather than in the user's home or a
    project — nothing of theirs is in reach, and the workspace-trust prompt
    (which blocks on stdin and hangs a headless call) has somewhere safe to
    apply to.
    """
    path = get_settings().home / "agent-workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def managed_binary(vendor: str) -> Path | None:
    """Our pinned copy, if we have installed one."""
    spec = SPECS.get(vendor)
    if not spec:
        return None
    path = managed_bin_dir() / spec.binary
    return path if path.exists() and os.access(path, os.X_OK) else None


# ── resolving the current release ────────────────────────────────────────
def _plat() -> tuple[str, str]:
    system = platform.system().lower()          # darwin
    machine = platform.machine().lower()        # arm64 | x86_64
    return system, machine


def _resolve_cursor() -> tuple[str, str, str]:
    """(version, url, kind). Cursor's install script names both."""
    script = httpx.get("https://cursor.com/install", timeout=30.0).text
    match = re.search(r"https://downloads\.cursor\.com/lab/([^/\"']+)/", script)
    if not match:
        raise RuntimeError("could not read the Cursor release from its install script")
    version = match.group(1)
    system, machine = _plat()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    url = (f"https://downloads.cursor.com/lab/{version}/{system}/{arch}/"
           "agent-cli-package.tar.gz")
    return version, url, "targz"


def _resolve_grok() -> tuple[str, str, str]:
    """(version, url, kind). x.ai/cli/stable returns the version string."""
    version = httpx.get("https://x.ai/cli/stable", timeout=30.0).text.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[A-Za-z0-9._]+)?", version):
        raise RuntimeError(f"unexpected Grok version string: {version!r}")
    system, machine = _plat()
    os_name = "macos" if system == "darwin" else system
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return version, f"https://x.ai/cli/grok-{version}-{os_name}-{arch}", "binary"


_RESOLVERS: dict[str, Callable[[], tuple[str, str, str]]] = {
    "cursor": _resolve_cursor,
    "grok": _resolve_grok,
}


def latest_release(vendor: str) -> tuple[str, str, str]:
    resolver = _RESOLVERS.get(vendor)
    if not resolver:
        raise KeyError(f"no installer for {vendor!r}")
    return resolver()


def installed_version(vendor: str) -> str | None:
    """The version directory our symlink points into."""
    binary = managed_binary(vendor)
    if not binary:
        return None
    try:
        target = Path(os.path.realpath(binary))
        root = managed_root() / vendor
        return target.relative_to(root).parts[0]
    except Exception:
        return None


# ── installing ───────────────────────────────────────────────────────────
def _link(spec: CliSpec, payload: Path) -> Path:
    bin_dir = managed_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    primary = bin_dir / spec.binary
    for name in (spec.binary, *spec.aliases):
        link = bin_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(payload)
    return primary


def _download(url: str, dest: Path, on_progress: Callable[[int, int], None]) -> None:
    with httpx.stream("GET", url, timeout=_TIMEOUT, follow_redirects=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=262_144):
                fh.write(chunk)
                done += len(chunk)
                on_progress(done, total)


def install_cli(vendor: str, on_progress: Callable[[str, int], None] | None = None) -> Path:
    """Download and pin a vendor CLI. Returns the path to the usable binary."""
    spec = SPECS[vendor]
    note = on_progress or (lambda _msg, _pct: None)

    note("Checking for the latest release…", 2)
    version, url, kind = latest_release(vendor)

    target_dir = managed_root() / vendor / version
    payload = target_dir / spec.binary
    if payload.exists():
        note("Already downloaded — linking.", 90)
        _link(spec, payload)
        note(f"{spec.display} {version} ready.", 100)
        return payload

    with tempfile.TemporaryDirectory(prefix=f"lodestone-{vendor}-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / ("payload.tar.gz" if kind == "targz" else spec.binary)

        def progress(done: int, total: int) -> None:
            mb = done / 1e6
            if total:
                pct = 5 + int(done / total * 75)
            else:
                # No content-length: approximate against a typical CLI size so
                # the bar still moves rather than sitting at one number.
                pct = 5 + min(int(mb / 60 * 75), 70)
            note(f"Downloading {spec.display} {version}… {mb:.1f} MB", min(pct, 80))

        note(f"Downloading {spec.display} {version}…", 5)
        _download(url, archive, progress)

        note("Unpacking…", 85)
        staged = tmp_path / "staged"
        staged.mkdir()
        if kind == "targz":
            with tarfile.open(archive, "r:gz") as tar:
                # The vendor archive nests everything one level down.
                for member in tar.getmembers():
                    parts = Path(member.name).parts
                    if len(parts) <= 1:
                        continue
                    member.name = str(Path(*parts[1:]))
                    tar.extract(member, staged, filter="data")
            found = next((p for p in staged.rglob("*")
                          if p.is_file() and p.name in (spec.binary, *spec.aliases)), None)
            if not found:
                raise RuntimeError(f"{spec.binary} not found in the {vendor} archive")
            # The vendor may name it differently (Cursor ships `cursor-agent`)
            # and may nest it — normalise to staged/<spec.binary> either way.
            if found != staged / spec.binary:
                shutil.move(str(found), str(staged / spec.binary))
        else:
            shutil.move(str(archive), staged / spec.binary)

        exe = staged / spec.binary
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        note("Verifying…", 92)
        try:
            res = subprocess.run([str(exe), "--version"], capture_output=True,
                                 text=True, timeout=30.0)
            if res.returncode != 0 and not (res.stdout or res.stderr).strip():
                raise RuntimeError("downloaded binary did not run")
        except Exception as exc:
            raise RuntimeError(f"{spec.display} failed to verify: {exc}") from exc

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(staged), str(target_dir))

    _link(spec, payload)
    note(f"{spec.display} {version} installed.", 100)
    return payload


def uninstall_cli(vendor: str) -> bool:
    """Remove our managed copy. Never touches a user's own installation."""
    spec = SPECS.get(vendor)
    if not spec:
        return False
    removed = False
    for name in (spec.binary, *spec.aliases):
        link = managed_bin_dir() / name
        if link.exists() or link.is_symlink():
            link.unlink()
            removed = True
    vendor_dir = managed_root() / vendor
    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
        removed = True
    return removed


# ── background job, so a UI refresh cannot kill an install ───────────────
@dataclass
class _Job:
    vendor: str
    state: str = "idle"          # idle | running | done | error
    message: str = ""
    percent: int = 0
    error: str = ""
    started_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_JOBS: dict[str, _Job] = {}


def install_status(vendor: str) -> dict[str, Any]:
    spec = SPECS.get(vendor)
    job = _JOBS.get(vendor)
    binary = managed_binary(vendor)
    return {
        "vendor": vendor,
        "display": spec.display if spec else vendor,
        "installable": vendor in SPECS,
        "installed": binary is not None,
        "path": str(binary) if binary else None,
        "version": installed_version(vendor),
        "docs_url": spec.docs_url if spec else "",
        "state": job.state if job else ("done" if binary else "idle"),
        "message": job.message if job else "",
        "percent": job.percent if job else (100 if binary else 0),
        "error": job.error if job else "",
    }


def start_install(vendor: str) -> dict[str, Any]:
    if vendor not in SPECS:
        raise KeyError(f"no installer for {vendor!r}")
    job = _JOBS.setdefault(vendor, _Job(vendor))
    with job.lock:
        if job.state == "running":
            return install_status(vendor)
        job.state, job.message, job.percent = "running", "Starting…", 0
        job.error, job.started_at = "", time.time()

    def run() -> None:
        def note(message: str, percent: int) -> None:
            job.message, job.percent = message, percent

        try:
            install_cli(vendor, note)
            job.state, job.percent = "done", 100
        except Exception as exc:
            job.state = "error"
            job.error = str(exc)[:200]
            job.message = f"Install failed: {job.error}"

    threading.Thread(target=run, daemon=True).start()
    return install_status(vendor)
