#!/bin/bash
# Build a double-clickable "Lodestone.app" for THIS machine, for development.
#
# The launcher it writes runs this checkout's virtualenv, so the bundle contains
# no Python and works nowhere else. That is the point — it is a fast way to get
# an icon in ~/Applications while developing.
#
# To build something you can give to somebody else, use scripts/build-dmg.sh:
# it bundles the interpreter with PyInstaller, signs with Developer ID, and
# notarises. See docs/DISTRIBUTION.md.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Read the version rather than restating it — this file said 0.2.0 while
# pyproject.toml said 0.1.0.
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -1)"
VENV="$PROJECT_DIR/.venv"
APP_DIR="${1:-$HOME/Applications}/Lodestone.app"
CONTENTS="$APP_DIR/Contents"

if [ ! -x "$VENV/bin/lodestone" ]; then
  echo "❌ venv not found at $VENV — run: uv venv && uv pip install -e '.[all,desktop]'"
  exit 1
fi

echo "Building $APP_DIR …"
rm -rf "$APP_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

# launcher
cat > "$CONTENTS/MacOS/Lodestone" <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
exec "$VENV/bin/lodestone" app
EOF
chmod +x "$CONTENTS/MacOS/Lodestone"

# Info.plist
cat > "$CONTENTS/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Lodestone</string>
  <key>CFBundleDisplayName</key><string>Lodestone</string>
  <key>CFBundleIdentifier</key><string>ai.lodestone.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>Lodestone</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# optional icon: if an icon.icns is present in scripts/, use it
if [ -f "$PROJECT_DIR/scripts/icon.icns" ]; then
  cp "$PROJECT_DIR/scripts/icon.icns" "$CONTENTS/Resources/icon.icns"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string icon" "$CONTENTS/Info.plist" 2>/dev/null || true
fi

echo "✓ Built $APP_DIR"
echo "  Open it from $HOME/Applications (or double-click). First launch: right-click → Open."
