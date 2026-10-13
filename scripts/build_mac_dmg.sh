#!/bin/bash
# Build a self-contained "Liscia Agent.app" (Python bundled, arm64) and a .dmg. macOS only.
# Usage: scripts/build_mac_dmg.sh   -> dist/Liscia-Agent-<ver>-macos-arm64.dmg
set -euo pipefail
cd "$(dirname "$0")/.."
VER="${VERSION:-1.1.1}"
PY="${PYTHON:-python3}"
[ -d build/venv ] || "$PY" -m venv build/venv
build/venv/bin/pip install -q -r requirements.txt pyinstaller
# icon.png -> AppIcon.icns
SRC=icon_mac.png; [ -f "$SRC" ] || SRC=icon.png
SET=build/AppIcon.iconset; rm -rf "$SET"; mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o build/AppIcon.icns
rm -rf "dist/Liscia Agent.app" "dist/Liscia Agent"
build/venv/bin/pyinstaller --noconfirm --clean liscia_agent.spec
APP="dist/Liscia Agent.app"
codesign --force --deep --sign - "$APP"          # ad-hoc signature
codesign --verify --deep --strict "$APP" && echo "codesign ok"
STAGE=build/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
DMG="dist/Liscia-Agent-$VER-macos-arm64.dmg"; rm -f "$DMG"
hdiutil create -volname "Liscia Agent $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "Built $DMG"
