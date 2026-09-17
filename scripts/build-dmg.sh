#!/bin/bash
# Build a distributable Chitragupta.dmg: bundle → sign → notarise → staple → dmg.
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
#                  way past is a trip through System Settings → Privacy &
#                  Security → Open Anyway — which is exactly the kind of
#                  instruction this product refuses to give (see CLAUDE.md).
#                  (It used to be right-click → Open. Apple removed that bypass
#                  in macOS 15, so the workaround got *worse*, not better.)
#   4. Staple      Attaches the ticket to the .dmg so first launch works with no
#                  network. Skipping it means an offline user is blocked.
#
# Requirements for a *distributable* build (steps 2-4):
#   * Apple Developer Program membership ($99/yr)
#   * A "Developer ID Application" certificate in the login keychain
#   * A notarytool keychain profile:
#       xcrun notarytool store-credentials chitragupta-notary \
#         --apple-id you@example.com --team-id TEAMID --password <app-specific-password>
#
# Without those, run with --unsigned to get a .dmg you can install yourself and
# hand to testers who are willing to walk through System Settings once. It is a
# real build; it is just not something a non-technical user can install. The
# image carries a READ ME FIRST.txt with the steps.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

APP_NAME="Chitragupta"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
DIST="$PROJECT_DIR/dist"
APP="$DIST/$APP_NAME.app"
# The architecture is in the filename because this build is whatever machine
# made it (arm64 here) and an Intel Mac cannot run it at all. Two files named
# `Chitragupta-0.1.0.dmg` on a download page is a support problem you cannot undo
# after the fact, so the name carries the answer from the first release.
ARCH="$(uname -m)"
DMG="$DIST/$APP_NAME-$VERSION-$ARCH.dmg"
STAGE="$DIST/dmg-stage"

SIGN_IDENTITY="${CHITRAGUPTA_SIGN_IDENTITY:-Developer ID Application}"
NOTARY_PROFILE="${CHITRAGUPTA_NOTARY_PROFILE:-chitragupta-notary}"
UNSIGNED=0
[ "${1:-}" = "--unsigned" ] && UNSIGNED=1

step() { printf "\n\033[1m▸ %s\033[0m\n" "$1"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

# ── 0. Preflight ────────────────────────────────────────────────────────────
step "Preflight"
[ -d .venv ] || die "No .venv — run: uv venv && uv pip install -e '.[desktop,gmail,gdrive,notion,telegram]'"
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
( cd packaging && "$PROJECT_DIR/.venv/bin/python" -m PyInstaller Chitragupta.spec \
    --noconfirm --distpath "$DIST" --workpath "$PROJECT_DIR/build" --log-level WARN )
[ -d "$APP" ] || die "PyInstaller produced no $APP_NAME.app"
echo "  size: $(du -sh "$APP" | cut -f1)"

# The spec's icon test was cwd-relative while PyInstaller runs from packaging/,
# so for the whole life of this script the bundle shipped PyInstaller's generic
# `icon-windowed.icns` and adding real artwork changed nothing visible. Assert
# the built plist rather than trusting the spec, because the failure looked
# exactly like success.
if [ -f packaging/icon.icns ]; then
  ICON_KEY="$(/usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" \
              "$APP/Contents/Info.plist" 2>/dev/null || echo "")"
  case "$ICON_KEY" in
    icon-windowed*|"") die "the bundle did not pick up packaging/icon.icns \
(CFBundleIconFile=${ICON_KEY:-unset}) — the spec's icon path is wrong again" ;;
    *) echo "  icon: $ICON_KEY ✓" ;;
  esac
else
  echo "  ! packaging/icon.icns is missing — the app will wear the generic icon."
  echo "    Generate it with:  ./.venv/bin/python packaging/make-icon.py"
fi

# The bundle is only useful if it actually starts. A build that produces a
# launchable-looking .app which dies on a missing hidden import is the failure
# mode this catches, and it costs fifteen seconds.
step "Smoke test: does it start and serve?"
SMOKE_HOME="$(mktemp -d)"
CHITRAGUPTA_HOME="$SMOKE_HOME" "$APP/Contents/MacOS/$APP_NAME" >"$SMOKE_HOME/out.log" 2>&1 &
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
else
  # PyInstaller ad-hoc signs the bundle on Apple Silicon, and an ad-hoc
  # signature that is broken or incomplete does NOT produce the "unverified
  # developer" dialog — it produces "Chitragupta is damaged and can't be opened",
  # which no Open Anyway sequence rescues and which reads to the user as a
  # corrupt download. Skipping the whole signing block used to skip this check
  # with it, so the build could not tell "will warn" from "will not open".
  step "Verifying the ad-hoc signature (unsigned build)"
  codesign --verify --deep --strict --verbose=2 "$APP" \
    || die "the bundle's ad-hoc signature is broken — macOS will call this
    .app damaged rather than merely unverified, and no user can get past that.
    Rebuild, and if it persists check for a stale dist/ or a quarantined file."
fi

# ── 3. Disk image ───────────────────────────────────────────────────────────
step "Building $(basename "$DMG")"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"    # the drag-to-install gesture

# An unsigned build cannot avoid Gatekeeper's dialog, but it can avoid the user
# meeting it uninformed. Without this the image is an app and a symlink, and the
# first thing that happens after the drag is a warning about malware with no
# context and a single "Done" button.
if [ "$UNSIGNED" = "1" ]; then
  cat > "$STAGE/READ ME FIRST.txt" <<'README'
Opening Chitragupta the first time
================================

Chitragupta is not yet signed with an Apple Developer certificate, so the first
time you open it macOS will say it "cannot be opened because Apple cannot check
it for malicious software". That is macOS telling you it does not recognise the
developer — it is not a virus warning, and it happens to every app distributed
outside the App Store without a paid certificate.

Here is how to open it. It only has to be done once.

  1. Drag Chitragupta to the Applications folder in this window.
  2. Open Applications and double-click Chitragupta. You will see the warning.
     Click Done.
  3. Open System Settings -> Privacy & Security.
  4. Scroll down. There is a line saying "Chitragupta was blocked", with an
     "Open Anyway" button next to it. Click it.
  5. Double-click Chitragupta again and click Open.

From then on it opens normally, like any other app.

Note: older instructions on the internet say to right-click the app and choose
Open. Apple removed that shortcut in macOS 15, so on any recent Mac the steps
above are the ones that work.

Requirements
------------
  * An Apple Silicon Mac (M1, M2, M3, M4 or later). Intel Macs are not
    supported.
  * macOS 11 or later.

Everything Chitragupta stores stays on this Mac, in your Library folder. It does
not upload your data anywhere.
README
fi
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

    Gatekeeper will tell anyone who opens it that the app cannot be checked for
    malicious software. Getting past it means:

        open it once and let it be blocked  →  System Settings
        →  Privacy & Security  →  scroll down  →  Open Anyway

    NOT right-click → Open. Apple removed that bypass in macOS 15, so any
    instructions still saying it will strand a tester on a current Mac. The
    image carries a READ ME FIRST.txt saying the above; send the same steps in
    whatever message you attach the file to.

    Fine for a handful of testers you can talk to. Not something to put on a
    download page — for that, notarise.
NOTE
fi
