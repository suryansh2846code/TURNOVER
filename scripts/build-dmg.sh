#!/bin/bash
# Build a distributable Lodestone.dmg: bundle → sign → notarise → staple → dmg.
#
# This is the "give it to somebody else" path. `scripts/build-macos-app.sh` is
# the other one, and it is NOT this: that writes a shim whose launcher runs this
# checkout's virtualenv, so it works on the machine that built it and nowhere
# else. Useful for development, useless as a download.
#
# What actually has to happen, and why each step is not optional:
#
#   1. Bundle      PyInstaller puts the interpreter, the dependencies and the
#                  web assets inside the .app. Without this there is no Python
#                  on the user's machine to run.
#   2. Sign        Developer ID Application + Hardened Runtime. Notarisation
#                  refuses anything without the Hardened Runtime, and CPython
#                  needs the exceptions in packaging/entitlements.plist to
#                  survive it.
#   3. Notarise    Apple scans the upload and issues a ticket. Without one,
#                  Gatekeeper tells the user the app "cannot be opened because
#                  Apple cannot check it for malicious software", and the only
#                  way past is right-click → Open — which is exactly the kind of
#                  instruction this product refuses to give (see CLAUDE.md).
#   4. Staple      Attaches the ticket to the .dmg so first launch works with no
#                  network. Skipping it means an offline user is blocked.
#
# Requirements for a *distributable* build (steps 2-4):
#   * Apple Developer Program membership ($99/yr)
#   * A "Developer ID Application" certificate in the login keychain
#   * A notarytool keychain profile:
#       xcrun notarytool store-credentials lodestone-notary \
#         --apple-id you@example.com --team-id TEAMID --password <app-specific-password>
#
# Without those, run with --unsigned to get a .dmg you can install yourself and
# hand to people who are willing to right-click → Open. It is a real build; it
# is just not something a non-technical user can install.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

APP_NAME="Lodestone"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
DIST="$PROJECT_DIR/dist"
APP="$DIST/$APP_NAME.app"
DMG="$DIST/$APP_NAME-$VERSION.dmg"
STAGE="$DIST/dmg-stage"

SIGN_IDENTITY="${LODESTONE_SIGN_IDENTITY:-Developer ID Application}"
NOTARY_PROFILE="${LODESTONE_NOTARY_PROFILE:-lodestone-notary}"
UNSIGNED=0
[ "${1:-}" = "--unsigned" ] && UNSIGNED=1

step() { printf "\n\033[1m▸ %s\033[0m\n" "$1"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

# ── 0. Preflight ────────────────────────────────────────────────────────────
step "Preflight"
[ -d .venv ] || die "No .venv — run: uv venv && uv pip install -e '.[desktop,gmail,gdrive,notion]'"
./.venv/bin/python -c "import webview" 2>/dev/null \
  || die "pywebview missing — run: uv pip install -e '.[desktop]'"
./.venv/bin/python -c "import PyInstaller" 2>/dev/null \
  || die "PyInstaller missing — run: uv pip install pyinstaller"

if ./.venv/bin/python -c "import torch" 2>/dev/null; then
  cat <<'WARN'
  ! torch is installed in .venv.

    The spec excludes it, so the bundle stays ~190 MB rather than ~2 GB — but a
    bundle built from an environment containing it is worth checking. Confirm
    the size at the end of this script before shipping.
WARN
fi

if [ "$UNSIGNED" = "0" ]; then
  security find-identity -v -p codesigning | grep -q "Developer ID Application" \
    || die "No 'Developer ID Application' certificate in the keychain.
    Get one from developer.apple.com (Apple Developer Program, \$99/yr),
    or build an installable-by-hand copy with:  $0 --unsigned"
  xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1 \
    || die "No notarytool profile '$NOTARY_PROFILE'. Create one with:
    xcrun notarytool store-credentials $NOTARY_PROFILE \\
      --apple-id you@example.com --team-id TEAMID --password <app-specific-password>"
fi

# ── 1. Bundle ───────────────────────────────────────────────────────────────
step "Building $APP_NAME.app (PyInstaller)"
rm -rf "$APP" "$DIST/$APP_NAME" "$STAGE" "$DMG"
( cd packaging && "$PROJECT_DIR/.venv/bin/python" -m PyInstaller Lodestone.spec \
    --noconfirm --distpath "$DIST" --workpath "$PROJECT_DIR/build" --log-level WARN )
[ -d "$APP" ] || die "PyInstaller produced no $APP_NAME.app"
echo "  size: $(du -sh "$APP" | cut -f1)"

# The bundle is only useful if it actually starts. A build that produces a
# launchable-looking .app which dies on a missing hidden import is the failure
# mode this catches, and it costs fifteen seconds.
step "Smoke test: does it start and serve?"
SMOKE_HOME="$(mktemp -d)"
LODESTONE_HOME="$SMOKE_HOME" "$APP/Contents/MacOS/$APP_NAME" >"$SMOKE_HOME/out.log" 2>&1 &
SMOKE_PID=$!
for _ in $(seq 1 30); do
  sleep 1
  PORT="$(cat "$SMOKE_HOME/.port" 2>/dev/null || true)"
  [ -n "$PORT" ] && curl -fsS -m 3 "http://127.0.0.1:$PORT/api/sync/status" >/dev/null 2>&1 && break
done
kill "$SMOKE_PID" 2>/dev/null || true
wait "$SMOKE_PID" 2>/dev/null || true
[ -n "${PORT:-}" ] || { sed -n '1,40p' "$SMOKE_HOME/out.log"; die "the bundled app never served a request"; }
echo "  served on port $PORT ✓"
rm -rf "$SMOKE_HOME"

# ── 2. Sign ─────────────────────────────────────────────────────────────────
if [ "$UNSIGNED" = "0" ]; then
  step "Signing (Developer ID + Hardened Runtime)"
  # Inside-out: every nested binary first, then the bundle. A single pass over
  # the .app leaves the dylibs and .so files unsigned and notarisation rejects
  # the whole upload for one of them.
  find "$APP" \( -name "*.dylib" -o -name "*.so" -o -perm +111 -type f \) -print0 \
  | while IFS= read -r -d '' bin; do
      codesign --force --timestamp --options runtime \
        --entitlements packaging/entitlements.plist \
        --sign "$SIGN_IDENTITY" "$bin" 2>/dev/null || true
    done
  codesign --force --timestamp --options runtime \
    --entitlements packaging/entitlements.plist \
    --sign "$SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
fi

# ── 3. Disk image ───────────────────────────────────────────────────────────
step "Building $(basename "$DMG")"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"    # the drag-to-install gesture
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO -quiet "$DMG"
rm -rf "$STAGE"

# ── 4. Notarise + staple ────────────────────────────────────────────────────
if [ "$UNSIGNED" = "0" ]; then
  step "Signing the disk image"
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"

  step "Notarising (this takes a few minutes — Apple is scanning it)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait \
    || die "Notarisation failed. See the log:
    xcrun notarytool log <submission-id> --keychain-profile $NOTARY_PROFILE"

  step "Stapling the ticket"
  # Without this the ticket is only fetchable online, so a user who installs
  # offline is still stopped by Gatekeeper.
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl --assess --type open --context context:primary-signature -v "$DMG"
fi

step "Done"
echo "  $DMG  ($(du -sh "$DMG" | cut -f1))"
if [ "$UNSIGNED" = "1" ]; then
  cat <<'NOTE'

  ! This build is UNSIGNED and NOT notarised.

    Gatekeeper will tell anyone who downloads it that the app cannot be checked
    for malicious software, and the only way past is right-click → Open. Fine
    for you and for a handful of testers you can talk to; not something to put
    on a download page.
NOTE
fi
