# `packaging/` — the shipped app

The PyInstaller spec, the Hardened Runtime entitlements, the bundled app's
launcher, and the icon generator.

**Paths here are anchored on `SPECPATH`, never on the working directory.**
`build-dmg.sh` invokes PyInstaller from inside this directory, so a
cwd-relative path in the spec resolves somewhere else than it reads — that is
how `icon.icns` silently never shipped, and how the bundle wore PyInstaller's
generic icon while the spec looked correct.

`icon.icns` is generated, not hand-drawn: `./.venv/bin/python
packaging/make-icon.py` renders it from the tokens in
[`docs/DESIGN-BRIEF.md`](../docs/DESIGN-BRIEF.md) so the icon cannot drift from
the identity it is meant to carry. It is deterministic — a change to it shows up
in review as an intentional diff.

Read [`docs/DISTRIBUTION.md`](../docs/DISTRIBUTION.md) before touching either
build script. They are not interchangeable:

- `scripts/build-dmg.sh` bundles, signs, notarises and staples a real `.dmg`
  (189 MB app → 74 MB image; torch is excluded deliberately).
- `scripts/build-macos-app.sh` is a **development shim** — its launcher runs
  *this checkout's* venv, so it works on this machine and nowhere else.

macOS is the only supported platform. Assume `~/Library/…`, Homebrew, and
`security` for the Keychain.

Rules: [`/CLAUDE.md`](../CLAUDE.md).
