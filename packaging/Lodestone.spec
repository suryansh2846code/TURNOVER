# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a self-contained Lodestone.app.

`scripts/build-macos-app.sh` writes a *shim* bundle whose launcher runs the
project's own virtualenv. That is a convenience for the machine it was built on
and cannot be given to anybody — there is no Python inside it. This spec builds
the real thing: interpreter, dependencies and web assets in one bundle.

Two decisions carry most of the size and most of the risk:

* **Torch is excluded.** `sentence-transformers` is an optional extra; the
  default embedder is the pure-Python `hash` one, which is why the app can run
  with no downloads at all. Bundling torch would add well over a gigabyte to
  every download for a feature most users never switch on. A user who wants
  local embeddings installs the extra into a source checkout.
* **The optional connector SDKs are declared as hidden imports.** They are
  imported inside functions so the app starts without them; PyInstaller's
  static analysis therefore cannot see them, and a bundle built without this
  list would ship an app whose Gmail connector fails at the moment it is used.
"""
import pathlib
import re

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

BLOCK_CIPHER = None

# One source of truth for the version. It was hardcoded here as 0.2.0 while
# pyproject.toml said 0.1.0 and the shim bundle's Info.plist said 0.2.0 — three
# numbers for one build, which is how a user reports a version that never
# existed.
VERSION = re.search(
    r'^version = "([^"]+)"',
    pathlib.Path("../pyproject.toml").read_text(), re.M).group(1)

# Imported lazily inside functions, so the analyser cannot find them.
HIDDEN = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "webview", "webview.platforms.cocoa",
    "googleapiclient", "google_auth_oauthlib", "google.auth",
    "notion_client", "pypdf", "docx", "pptx", "ddgs",
    "anyio._backends._asyncio",
]
HIDDEN += collect_submodules("lodestone")

# Everything the server serves. `lodestone/web` is read from disk at runtime by
# `api/assets.py::WEB`, so it has to travel with the bundle.
DATAS = [
    ("../lodestone/web", "lodestone/web"),
    ("../lodestone/data", "lodestone/data"),
]
DATAS += collect_data_files("ddgs", include_py_files=False)

# Large optional dependencies, and anything that only exists to build wheels.
EXCLUDED = [
    "torch", "sentence_transformers", "transformers", "scipy", "sklearn",
    "matplotlib", "pandas", "IPython", "notebook", "pytest", "mypy", "ruff",
    "tkinter", "PIL", "PyQt5", "PySide6",
]

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED,
    cipher=BLOCK_CIPHER,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=BLOCK_CIPHER)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Lodestone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX-packed binaries fail notarisation
    console=False,             # a GUI app: no terminal window
    target_arch=None,          # whatever this machine is; see docs/DISTRIBUTION.md
    codesign_identity=None,    # signed as one bundle later, not per-binary
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="Lodestone",
)

app = BUNDLE(
    coll,
    name="Lodestone.app",
    icon="icon.icns" if __import__("pathlib").Path("packaging/icon.icns").exists() else None,
    bundle_identifier="ai.lodestone.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "Lodestone",
        "CFBundleDisplayName": "Lodestone",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # Lodestone is a window, not a menu-bar accessory. (An accessory policy
        # is what would let the sign-in card float over another app's
        # full-screen Space — see docs/DESKTOP-SIGNIN.md for why that trade was
        # refused.)
        "LSUIElement": False,
        # Shown in the macOS permission prompts. These strings are the entire
        # explanation the user gets, so they say what Lodestone does with the
        # data and that it stays on the machine.
        "NSAppleEventsUsageDescription":
            "Lodestone reads your Notes and Calendar to build your local brain. "
            "Nothing leaves your Mac.",
        "NSCalendarsUsageDescription":
            "Lodestone reads your calendar so your agents know your schedule. "
            "It stays on this Mac.",
        "NSContactsUsageDescription":
            "Lodestone reads your contacts so it can recognise the people you "
            "work with. It stays on this Mac.",
        "NSDesktopFolderUsageDescription":
            "Lodestone indexes folders you choose so your agents can search them.",
        "NSDocumentsFolderUsageDescription":
            "Lodestone indexes folders you choose so your agents can search them.",
        "NSDownloadsFolderUsageDescription":
            "Lodestone indexes folders you choose so your agents can search them.",
    },
)
