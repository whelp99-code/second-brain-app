#!/usr/bin/env python3
"""Static pre-device gate for Phone History iOS sources and privacy boundaries."""

from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
EVIDENCE = ROOT / "evidence"
REPORT = EVIDENCE / "predevice-static-report.json"


def check(condition: bool, name: str, details: str, results: list[dict[str, Any]]) -> None:
    results.append({"name": name, "passed": bool(condition), "details": details})


def run(command: list[str], cwd: Path = ROOT) -> tuple[bool, str]:
    process = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    output = (process.stdout + process.stderr).strip()
    return process.returncode == 0, output[-4000:]


def load_plist(path: Path) -> dict[str, Any]:
    return plistlib.loads(path.read_bytes())


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for script in ("generate_ios_contract.py", "generate_ios_api_paths.py"):
        ok, output = run([sys.executable, str(ROOT / "scripts" / script)])
        check(ok, f"generator:{script}", output or "generated", results)

    required = [
        IOS / "project.yml",
        IOS / "Config" / "PhoneHistory.xcconfig",
        IOS / "Core" / "GeneratedContract.swift",
        IOS / "Core" / "GeneratedAPIPaths.swift",
        IOS / "App" / "PhoneHistoryApp.swift",
        IOS / "ShareExtension" / "ShareViewController.swift",
        IOS / "Tests" / "PhoneHistoryCoreTests.swift",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    check(not missing, "required-files", "missing=" + ",".join(missing), results)

    app_info = load_plist(IOS / "App" / "Info.plist")
    share_info = load_plist(IOS / "ShareExtension" / "Info.plist")
    app_entitlements = load_plist(IOS / "App" / "PhoneHistory.entitlements")
    share_entitlements = load_plist(IOS / "ShareExtension" / "PhoneHistoryShare.entitlements")
    app_privacy = load_plist(IOS / "App" / "PrivacyInfo.xcprivacy")
    share_privacy = load_plist(IOS / "ShareExtension" / "PrivacyInfo.xcprivacy")

    app_groups = app_entitlements.get("com.apple.security.application-groups")
    share_groups = share_entitlements.get("com.apple.security.application-groups")
    app_keychain = app_entitlements.get("keychain-access-groups")
    share_keychain = share_entitlements.get("keychain-access-groups")
    check(
        app_groups == share_groups == ["$(PHONE_HISTORY_APP_GROUP)"],
        "entitlements:app-group-parity",
        f"app={app_groups!r} share={share_groups!r}",
        results,
    )
    check(
        app_keychain == share_keychain == ["$(PHONE_HISTORY_KEYCHAIN_GROUP)"],
        "entitlements:keychain-parity",
        f"app={app_keychain!r} share={share_keychain!r}",
        results,
    )
    forbidden_entitlements = {
        "com.apple.developer.family-controls",
        "com.apple.developer.networking.networkextension",
        "com.apple.developer.homekit",
    }
    used_entitlements = set(app_entitlements) | set(share_entitlements)
    check(
        not (used_entitlements & forbidden_entitlements),
        "entitlements:minimal-scope",
        f"used={sorted(used_entitlements)}",
        results,
    )

    ats = app_info.get("NSAppTransportSecurity", {})
    check(
        not ats.get("NSAllowsArbitraryLoads", False),
        "privacy:no-arbitrary-http",
        repr(ats),
        results,
    )
    usage_keys = [key for key in app_info if key.endswith("UsageDescription")]
    check(
        usage_keys == ["NSHealthShareUsageDescription"]
        and bool(app_info.get("NSHealthShareUsageDescription")),
        "privacy:only-health-read-permission",
        f"usageDescriptionKeys={usage_keys}",
        results,
    )
    activation = (
        share_info.get("NSExtension", {})
        .get("NSExtensionAttributes", {})
        .get("NSExtensionActivationRule")
    )
    check(
        activation != "TRUEPREDICATE" and isinstance(activation, dict),
        "share:bounded-activation-rule",
        repr(activation),
        results,
    )
    expected_collected_types = {
        "NSPrivacyCollectedDataTypeOtherUserContent",
        "NSPrivacyCollectedDataTypePhotosorVideos",
        "NSPrivacyCollectedDataTypeAudioData",
        "NSPrivacyCollectedDataTypeBrowsingHistory",
        "NSPrivacyCollectedDataTypeDeviceID",
    }
    for name, manifest in (("app", app_privacy), ("share", share_privacy)):
        collected = manifest.get("NSPrivacyCollectedDataTypes", [])
        collected_types = {
            item.get("NSPrivacyCollectedDataType") for item in collected if isinstance(item, dict)
        }
        collection_is_bounded = all(
            isinstance(item, dict)
            and item.get("NSPrivacyCollectedDataTypeLinked") is True
            and item.get("NSPrivacyCollectedDataTypeTracking") is False
            and item.get("NSPrivacyCollectedDataTypePurposes")
            == ["NSPrivacyCollectedDataTypePurposeAppFunctionality"]
            for item in collected
        )
        accessed = manifest.get("NSPrivacyAccessedAPITypes", [])
        app_group_defaults_declared = any(
            isinstance(item, dict)
            and item.get("NSPrivacyAccessedAPIType") == "NSPrivacyAccessedAPICategoryUserDefaults"
            and "1C8F.1" in item.get("NSPrivacyAccessedAPITypeReasons", [])
            for item in accessed
        )
        check(
            manifest.get("NSPrivacyTracking") is False
            and collected_types
            == (
                expected_collected_types
                | (
                    {"NSPrivacyCollectedDataTypeHealth", "NSPrivacyCollectedDataTypeFitness"}
                    if name == "app"
                    else set()
                )
            )
            and collection_is_bounded
            and app_group_defaults_declared,
            f"privacy-manifest:{name}",
            (
                "explicit user content; linked=true; tracking=false; purpose=app "
                "functionality; App Group UserDefaults=1C8F.1"
            ),
            results,
        )

    from life_privacy import health_boundary_errors

    health_errors = health_boundary_errors(IOS)
    check(not health_errors, "life:opt-in-health-and-target-boundary", repr(health_errors), results)

    swift_files = sorted(IOS.rglob("*.swift"))
    swift_text = "\n".join(path.read_text(encoding="utf-8") for path in swift_files)
    forbidden_apis = [
        "UIPasteboard.general",
        "AVAudioRecorder",
        "SFSpeechRecognizer",
        "FamilyControls",
        "DeviceActivity",
        "NEPacketTunnelProvider",
        "RPSystemBroadcastPickerView",
    ]
    used_forbidden = [name for name in forbidden_apis if name in swift_text]
    check(not used_forbidden, "source:no-surveillance-apis", repr(used_forbidden), results)
    check(
        'try ContractJSON.set("canonical", false' in swift_text
        and 'try ContractJSON.set("canonical", true' not in swift_text,
        "source:no-canonical-auto-approval",
        "canonical is initialized false only",
        results,
    )
    check(
        "AES.GCM.seal" in swift_text and "AES.GCM.open" in swift_text,
        "source:aes-gcm-queue",
        "authenticated encryption and verification are present",
        results,
    )
    project_spec = (IOS / "project.yml").read_text(encoding="utf-8")
    share_target = project_spec.split("  PhoneHistoryShare:", 1)[1].split(
        "  PhoneHistoryTests:", 1
    )[0]
    check(
        "Core/APIClient.swift" not in share_target
        and "Core/SyncService.swift" not in share_target
        and "- path: Core\n" not in share_target,
        "share:network-code-excluded-from-target",
        "Share Extension compiles only capture and encrypted-queue Core files",
        results,
    )

    share_text = (IOS / "ShareExtension" / "ShareViewController.swift").read_text(encoding="utf-8")
    check(
        "markAsADotCallRecording" in share_text
        and "isLikelyAudio" in share_text
        and "URLSession" not in share_text,
        "share:user-declared-adot-and-queue-only",
        "A-dot classification is explicit; extension performs no network upload",
        results,
    )
    check(
        "Data(contentsOf: url, options: [.mappedIfSafe])" not in share_text,
        "share:copies-provider-file-before-return",
        "provider temporary file is copied, not memory-mapped",
        results,
    )

    if shutil.which("swiftc"):
        parse_failures: list[str] = []
        for path in swift_files:
            ok, output = run(["swiftc", "-frontend", "-parse", str(path)])
            if not ok:
                parse_failures.append(f"{path.relative_to(ROOT)}: {output}")
        check(
            not parse_failures,
            "swift:syntax-parse",
            "\n".join(parse_failures) if parse_failures else f"parsed {len(swift_files)} files",
            results,
        )
    else:
        results.append(
            {
                "name": "swift:syntax-parse",
                "passed": None,
                "details": (
                    "swiftc unavailable on this Ubuntu host; xcodebuild gate remains "
                    "device-host only"
                ),
            }
        )

    if shutil.which("xcodegen"):
        generated = EVIDENCE / "xcodegen-check"
        if generated.exists():
            shutil.rmtree(generated)
        generated.mkdir()
        ok, output = run(
            [
                "xcodegen",
                "generate",
                "--spec",
                str(IOS / "project.yml"),
                "--project",
                str(generated),
            ]
        )
        check(ok, "xcodegen:project-generation", output or "generated", results)
    else:
        results.append(
            {
                "name": "xcodegen:project-generation",
                "passed": None,
                "details": (
                    "xcodegen unavailable on this Ubuntu host; generation script "
                    "validates this on macOS"
                ),
            }
        )

    failed = [item for item in results if item["passed"] is False]
    report = {
        "schema": "phone-history-predevice-static-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": sys.platform,
        "result": "PASS" if not failed else "FAIL",
        "checks": results,
        "device_only_gates": [
            "xcodebuild for generic iOS and simulator",
            "Apple Team signing and entitlement provisioning",
            "Share Extension from Safari, Files, Photos, and A-dot",
            "protected-data reboot/lock behavior",
            "BGTask scheduling observation",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
