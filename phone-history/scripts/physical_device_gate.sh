#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_UDID="${PHONE_HISTORY_DEVICE_UDID:-${1:-}}"
[[ -n "$DEVICE_UDID" ]] || {
  echo "Usage: PHONE_HISTORY_DEVICE_UDID=<udid> $0" >&2
  exit 2
}
[[ "$(uname -s)" == "Darwin" ]] || { echo "ERROR: macOS required"; exit 2; }
for command in python3 xcodegen xcodebuild xcrun; do
  command -v "$command" >/dev/null || { echo "ERROR: missing $command"; exit 2; }
done

TEAM_ID="${PHONE_HISTORY_DEVELOPMENT_TEAM:-}"
[[ "$TEAM_ID" =~ ^[A-Z0-9]{10}$ ]] || {
  echo "ERROR: set PHONE_HISTORY_DEVELOPMENT_TEAM to the 10-character Apple Developer Team ID" >&2
  exit 2
}

EVIDENCE="$ROOT/evidence/device-$(date -u +%Y%m%dT%H%M%SZ)"
DERIVED="$EVIDENCE/DerivedData"
mkdir -p "$EVIDENCE"
exec > >(tee "$EVIDENCE/gate.log") 2>&1
cd "$ROOT"

python3 scripts/generate_ios_contract.py
python3 scripts/generate_ios_api_paths.py
python3 scripts/verify_ios_static.py
if [[ -f evidence/release-manifest.json ]]; then
  python3 scripts/build_release_manifest.py --verify evidence/release-manifest.json
fi
rm -rf ios/PhoneHistory.xcodeproj
xcodegen generate --spec ios/project.yml --project ios
xcrun devicectl list devices | tee "$EVIDENCE/connected-devices.log"

xcodebuild \
  -project ios/PhoneHistory.xcodeproj \
  -scheme PhoneHistory \
  -configuration Debug \
  -destination "id=$DEVICE_UDID" \
  -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  PHONE_HISTORY_DEVELOPMENT_TEAM="$TEAM_ID" \
  clean build | tee "$EVIDENCE/device-build.log"

xcodebuild \
  -project ios/PhoneHistory.xcodeproj \
  -scheme PhoneHistory \
  -configuration Debug \
  -destination "id=$DEVICE_UDID" \
  -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  PHONE_HISTORY_DEVELOPMENT_TEAM="$TEAM_ID" \
  test | tee "$EVIDENCE/device-tests.log"

APP_PATH="$(find "$DERIVED/Build/Products" -type d \( -name '폰 히스토리.app' -o -name 'PhoneHistory.app' \) | head -n 1)"
[[ -n "$APP_PATH" && -d "$APP_PATH" ]] || { echo "ERROR: built app not found"; exit 1; }
xcrun devicectl device install app --device "$DEVICE_UDID" "$APP_PATH" | tee "$EVIDENCE/device-install.log"
xcrun devicectl device process launch --device "$DEVICE_UDID" com.blro.phonehistory | tee "$EVIDENCE/device-launch.log" || true

cat > "$EVIDENCE/result.json" <<JSON
{
  "schema": "phone-history-physical-device-gate-v1",
  "automated_result": "PASS",
  "manual_result": "PENDING",
  "device_udid": "$DEVICE_UDID",
  "app_path": "$APP_PATH",
  "closure": "NOT_APPROVED"
}
JSON

cat <<'CHECKLIST'
AUTOMATED DEVICE GATE: PASS
MANUAL GATE: PENDING
Run docs/DEVICE-VALIDATION-HANDOFF.md sections D1-D12 on the connected iPhone.
Do not declare device closure until the completed checklist and exported evidence are present.
CHECKLIST

echo "EVIDENCE: $EVIDENCE"
