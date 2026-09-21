#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: Xcode project generation must run on macOS." >&2
  exit 2
fi
for command in python3 xcodegen xcodebuild; do
  command -v "$command" >/dev/null || { echo "ERROR: missing $command" >&2; exit 2; }
done

python3 scripts/generate_ios_contract.py
python3 scripts/generate_ios_api_paths.py
python3 scripts/verify_ios_static.py
rm -rf ios/PhoneHistory.xcodeproj
xcodegen generate --spec ios/project.yml --project ios
xcodebuild -project ios/PhoneHistory.xcodeproj -scheme PhoneHistory -list

echo "GENERATED: $ROOT/ios/PhoneHistory.xcodeproj"
