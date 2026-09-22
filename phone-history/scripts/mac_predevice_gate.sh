#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE="$ROOT/evidence/mac-predevice-$(date -u +%Y%m%dT%H%M%SZ)"
DERIVED="$EVIDENCE/DerivedData"
mkdir -p "$EVIDENCE"
exec > >(tee "$EVIDENCE/gate.log") 2>&1

[[ "$(uname -s)" == "Darwin" ]] || { echo "ERROR: macOS required"; exit 2; }
for command in python3 xcodegen xcodebuild xcrun; do
  command -v "$command" >/dev/null || { echo "ERROR: missing $command"; exit 2; }
done

cd "$ROOT"
python3 scripts/generate_ios_contract.py
python3 scripts/generate_ios_api_paths.py
python3 scripts/verify_ios_static.py
if [[ -f evidence/release-manifest.json ]]; then
  python3 scripts/build_release_manifest.py --verify evidence/release-manifest.json
fi
rm -rf ios/PhoneHistory.xcodeproj
xcodegen generate --spec ios/project.yml --project ios

xcodebuild \
  -project ios/PhoneHistory.xcodeproj \
  -scheme PhoneHistory \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  clean build | tee "$EVIDENCE/simulator-build.log"

SIMULATOR_UDID="$(python3 scripts/select_ios_simulator.py)"
xcrun simctl boot "$SIMULATOR_UDID" 2>/dev/null || true
xcrun simctl bootstatus "$SIMULATOR_UDID" -b
xcodebuild \
  -project ios/PhoneHistory.xcodeproj \
  -scheme PhoneHistory \
  -configuration Debug \
  -destination "id=$SIMULATOR_UDID" \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  test | tee "$EVIDENCE/simulator-tests.log"

python3 - "$EVIDENCE" "$SIMULATOR_UDID" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1])/'result.json'
path.write_text(json.dumps({
  'schema':'phone-history-mac-predevice-gate-v1',
  'result':'PASS',
  'simulator_udid':sys.argv[2],
  'next_gate':'physical-device',
},indent=2)+'\n')
PY

echo "MAC PREDEVICE GATE: PASS"
echo "EVIDENCE: $EVIDENCE"
