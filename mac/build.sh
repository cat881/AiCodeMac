#!/usr/bin/env bash
# Build AiCode.app (macOS). Requires: Xcode command line tools (clang), python3.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/AiCode.app"
BUNDLE_ID="com.cat881.aicodemac"
VERSION="${VERSION:-1.0.0}"
ARCH="$(uname -m)"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> Compiling native shell"
clang -fobjc-arc -O2 -Wall \
  -arch "$ARCH" -mmacosx-version-min=12.0 \
  -framework Cocoa -framework WebKit \
  -o "$APP/Contents/MacOS/AiCode" "$ROOT/mac/main.m"

echo "==> Icon"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET"
python3 "$ROOT/mac/make-icon.py" "$ICONSET"
if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"; then
  echo "    AppIcon.icns ok"
else
  echo "    icon conversion failed, continuing without icon"
fi

echo "==> Bundling backend + web"
mkdir -p "$APP/Contents/Resources/app"
cp -R "$ROOT/server" "$APP/Contents/Resources/app/server"
cp -R "$ROOT/web" "$APP/Contents/Resources/app/web"
find "$APP/Contents/Resources/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$APP/Contents/Resources/app" -name '*.pyc' -delete 2>/dev/null || true

echo "==> Info.plist"
cp "$ROOT/mac/Info.plist" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"

echo "==> Ad-hoc codesign"
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "    codesign unavailable, skipping"
codesign --verify --deep --strict "$APP" 2>/dev/null && echo "    signature ok" || true

echo "==> Done: $APP"
du -sh "$APP"
