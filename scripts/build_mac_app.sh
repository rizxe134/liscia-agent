#!/bin/bash
# Build "PC Agent.app" (macOS only) that launches this folder's .venv. Usage: scripts/build_mac_app.sh [/Applications]
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/PC Agent.app"
[ -x "$DIR/.venv/bin/python" ] || { echo "Create the venv first (see README)."; exit 1; }
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/PCAgent" <<SH
#!/bin/bash
DIR="$DIR"
LOG="\$DIR/app.log"
cd "\$DIR" || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:\$PATH"
echo "=== PC Agent launch \$(date) ===" >> "\$LOG"
if ! curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null; then
  (open -ga Ollama 2>/dev/null || nohup ollama serve >> "\$DIR/ollama.log" 2>&1 &)
  for i in \$(seq 1 20); do curl -s --max-time 1 http://localhost:11434/api/tags >/dev/null && break; sleep 1; done
fi
export PYTHONUNBUFFERED=1
exec "\$DIR/.venv/bin/python" agent.py >> "\$LOG" 2>&1
SH
chmod +x "$APP/Contents/MacOS/PCAgent"
cat > "$APP/Contents/Info.plist" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>PC Agent</string>
<key>CFBundleDisplayName</key><string>PC Agent</string>
<key>CFBundleIdentifier</key><string>local.pcagent</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>PCAgent</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>NSHighResolutionCapable</key><true/>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSAppleEventsUsageDescription</key><string>PC Agent controls apps to complete tasks you ask for.</string>
</dict></plist>
PL
# icon: icon.png -> AppIcon.icns
TMP="$(mktemp -d)"; SET="$TMP/AppIcon.iconset"; mkdir "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$DIR/icon.png" --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$DIR/icon.png" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$APP/Contents/Resources/AppIcon.icns" && rm -rf "$TMP"
touch "$APP"
echo "Built $APP - open it from Finder/Launchpad/Spotlight."
