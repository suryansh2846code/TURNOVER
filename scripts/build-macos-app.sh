#!/bin/bash
# Build a double-clickable macOS "Lodestone.app" that launches the native window.
# It references this project's virtualenv (not a fully self-contained bundle),
# so it runs on THIS machine. Distribution to other Macs needs PyInstaller +
# code signing (a further step, heavy because of torch).
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
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
  <key>CFBundleVersion</key><string>0.2.0</string>
  <key>CFBundleShortVersionString</key><string>0.2.0</string>
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
