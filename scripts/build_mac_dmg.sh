#!/bin/bash
# Build a self-contained "PC Agent.app" (Python bundled, arm64) and a .dmg. macOS only.
# Usage: scripts/build_mac_dmg.sh   -> dist/PC-Agent-<ver>-macos-arm64.dmg
set -euo pipefail
cd "$(dirname "$0")/.."
VER="${VERSION:-1.0.0}"
PY="${PYTHON:-python3}"
[ -d build/venv ] || "$PY" -m venv build/venv
build/venv/bin/pip install -q -r requirements.txt pyinstaller
# icon.png -> AppIcon.icns
SET=build/AppIcon.iconset; rm -rf "$SET"; mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s icon.png --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) icon.png --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o build/AppIcon.icns
rm -rf "dist/PC Agent.app" "dist/PC Agent"
build/venv/bin/pyinstaller --noconfirm --clean pc_agent.spec
APP="dist/PC Agent.app"
codesign --force --deep --sign - "$APP"          # ad-hoc signature
codesign --verify --deep --strict "$APP" && echo "codesign ok"
STAGE=build/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
DMG="dist/PC-Agent-$VER-macos-arm64.dmg"; rm -f "$DMG"
hdiutil create -volname "PC Agent $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "Built $DMG"
