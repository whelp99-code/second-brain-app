#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Second Brain macOS app must be built on macOS with Xcode Command Line Tools." >&2
  exit 1
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

swift test
swift build -c release --product SecondBrainMac
BIN_DIR=$(swift build -c release --show-bin-path)
APP_DIR="$ROOT/dist/Second Brain.app"
CONTENTS="$APP_DIR/Contents"

rm -rf "$APP_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
install -m 0755 "$BIN_DIR/SecondBrainMac" "$CONTENTS/MacOS/SecondBrainMac"
install -m 0644 "$ROOT/Resources/Info.plist" "$CONTENTS/Info.plist"

/usr/bin/codesign --force --deep --sign - "$APP_DIR"
/usr/bin/codesign --verify --deep --strict "$APP_DIR"
/usr/bin/plutil -lint "$CONTENTS/Info.plist"

echo "$APP_DIR"
