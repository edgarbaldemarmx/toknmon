#!/bin/bash
# Build ToknMon.app (the macOS menu-bar app) with py2app from daemon/.venv,
# ad-hoc sign it and wrap it in a DMG.
#
# Usage: tools/build_mac_app.sh            # -> $OUT/dist/ToknMon.app, $OUT/ToknMon-<version>.dmg
#   OUT=/path/to/build-dir                 # default /tmp/toknmon-app-build (never inside the repo)
#
# Needs daemon/requirements-gui.txt installed in the venv (rumps, py2app):
#   daemon/.venv/bin/python -m pip install -r daemon/requirements-gui.txt
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/daemon/.venv/bin/python"
OUT="${OUT:-/tmp/toknmon-app-build}"
VERSION="$(tr -d '[:space:]' < "$ROOT/daemon/VERSION" 2>/dev/null || true)"
VERSION="${VERSION:-dev}"
APP="$OUT/dist/ToknMon.app"
DMG="$OUT/ToknMon-$VERSION.dmg"

if [ ! -x "$PY" ]; then
    echo "error: $PY not found — run ./install-mac.sh first" >&2
    exit 1
fi
if ! "$PY" -c "import rumps, py2app" 2>/dev/null; then
    echo "error: rumps/py2app missing — $PY -m pip install -r daemon/requirements-gui.txt" >&2
    exit 1
fi
case "$OUT" in
    "$ROOT"|"$ROOT"/*) echo "error: OUT must be outside the repository ($OUT)" >&2; exit 1 ;;
esac

rm -rf "$OUT/dist" "$OUT/build"
mkdir -p "$OUT"

echo "==> py2app build (version $VERSION) into $OUT"
# Run with $OUT as cwd so setuptools' egg-info and py2app scratch never land in
# the repository; setup_app.py resolves its own paths.
(cd "$OUT" && "$PY" "$ROOT/daemon/gui/setup_app.py" py2app \
    --dist-dir "$OUT/dist" --bdist-base "$OUT/build")

echo "==> ad-hoc codesign"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> DMG"
rm -f "$DMG"
hdiutil create -volname ToknMon -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null

echo "app: $APP ($(du -sh "$APP" | cut -f1))"
echo "dmg: $DMG ($(du -sh "$DMG" | cut -f1))"
