# `packaging/` — the shipped app

The PyInstaller spec, the Hardened Runtime entitlements and the bundled app's
launcher.

Read [`docs/DISTRIBUTION.md`](../docs/DISTRIBUTION.md) before touching either
build script. They are not interchangeable:

- `scripts/build-dmg.sh` bundles, signs, notarises and staples a real `.dmg`
  (189 MB app → 74 MB image; torch is excluded deliberately).
- `scripts/build-macos-app.sh` is a **development shim** — its launcher runs
  *this checkout's* venv, so it works on this machine and nowhere else.

macOS is the only supported platform. Assume `~/Library/…`, Homebrew, and
`security` for the Keychain.

Rules: [`/CLAUDE.md`](../CLAUDE.md).
