#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP="$ROOT/dist/Second Brain.app"
DESTINATION=${1:-"$HOME/Applications"}

if [[ ! -d "$APP" ]]; then
  "$ROOT/Scripts/build-app.sh" >/dev/null
fi

mkdir -p "$DESTINATION"
rm -rf "$DESTINATION/Second Brain.app"
cp -R "$APP" "$DESTINATION/Second Brain.app"
open "$DESTINATION/Second Brain.app"

echo "$DESTINATION/Second Brain.app"
