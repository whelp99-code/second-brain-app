#!/usr/bin/env python3
"""Build the machine-readable Phone History handoff after all pre-device gates pass."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EVIDENCE = ROOT / "evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    gate = json.loads((EVIDENCE / "predevice-gate-result.json").read_text(encoding="utf-8"))
    manifest = json.loads((EVIDENCE / "release-manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    archive = ROOT / "dist" / f"phone-history-{version}.tar.gz"
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    if gate.get("result") != "PASS" or gate.get("closure") != "READY_FOR_DEVICE_VALIDATION":
        raise SystemExit("predevice gate is not ready")
    if gate.get("pytest", {}).get("failures", 0) or gate.get("pytest", {}).get("errors", 0):
        raise SystemExit("test failures are present")
    if not archive.is_file() or not checksum.is_file():
        raise SystemExit("release archive or checksum is missing")
    expected_archive_hash = checksum.read_text(encoding="utf-8").split()[0]
    actual_archive_hash = sha256(archive)
    if expected_archive_hash != actual_archive_hash:
        raise SystemExit("external archive checksum mismatch")

    team_config = (ROOT / "ios/Config/PhoneHistory.xcconfig").read_text(encoding="utf-8")
    for line in team_config.splitlines():
        if line.strip().startswith("PHONE_HISTORY_DEVELOPMENT_TEAM"):
            configured = line.split("=", 1)[1].strip()
            if configured:
                raise SystemExit("Apple Team ID must not be persisted in source config")

    status = subprocess.run(
        ["git", "status", "--short", "--", "phone-history"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    handoff = {
        "schema": "phone-history-final-handoff-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "version": version,
        "implementation": "COMPLETE_PREDEVICE",
        "predevice_gate": "PASS",
        "predevice_closure": "READY_FOR_DEVICE_VALIDATION",
        "tests": gate.get("pytest", {}),
        "source_tree_sha256": manifest["source_tree_sha256"],
        "source_file_count": manifest["file_count"],
        "source_total_bytes": manifest["total_bytes"],
        "archive": str(archive),
        "archive_sha256_file": str(checksum),
        "archive_sha256": actual_archive_hash,
        "device_gate": "PENDING",
        "device_closure": "NOT_APPROVED",
        "pending_external_inputs": [
            "macOS Xcode host",
            "connected and trusted iPhone UDID",
            "Apple Developer Team ID supplied via environment",
            "provisioned App Group and Keychain Sharing identifiers",
            "Phone History HTTPS endpoint and device API token",
            "A-dot call recording sample supplied by the user",
        ],
        "required_device_checks": "docs/DEVICE-VALIDATION-HANDOFF.md D1-D12",
        "git_commit_created": False,
        "git_push_performed": False,
        "scoped_git_status": status,
    }
    output = EVIDENCE / "final-handoff.json"
    output.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(handoff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
