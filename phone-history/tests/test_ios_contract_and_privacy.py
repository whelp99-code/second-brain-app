from __future__ import annotations

import hashlib
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_generator(name: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_ios_contract_generation_matches_current_schema_and_fixture() -> None:
    run_generator("generate_ios_contract.py")
    generated = (ROOT / "ios/Core/GeneratedContract.swift").read_text(encoding="utf-8")
    schema_hash = hashlib.sha256(
        (ROOT / "contracts/phone-event-v1.schema.json").read_bytes()
    ).hexdigest()
    fixture_hash = hashlib.sha256(
        (ROOT / "contracts/fixtures/event-batch.json").read_bytes()
    ).hexdigest()
    assert f'static let schemaSHA256 = "{schema_hash}"' in generated
    assert f'static let fixtureSHA256 = "{fixture_hash}"' in generated
    assert '"device_id"' in generated
    assert '"content_base64"' in generated
    assert '"sha256"' in generated


def test_ios_api_generation_matches_current_openapi() -> None:
    run_generator("generate_ios_api_paths.py")
    generated = (ROOT / "ios/Core/GeneratedAPIPaths.swift").read_text(encoding="utf-8")
    openapi_hash = hashlib.sha256((ROOT / "contracts/openapi.yaml").read_bytes()).hexdigest()
    assert f'static let openAPISHA256 = "{openapi_hash}"' in generated
    batch_line = next(line for line in generated.splitlines() if "batchIngest =" in line)
    assert '""' not in batch_line


def test_app_and_share_extension_use_the_same_minimal_groups() -> None:
    app = plistlib.loads((ROOT / "ios/App/PhoneHistory.entitlements").read_bytes())
    share = plistlib.loads(
        (ROOT / "ios/ShareExtension/PhoneHistoryShare.entitlements").read_bytes()
    )
    assert (
        app["com.apple.security.application-groups"]
        == share["com.apple.security.application-groups"]
        == ["$(PHONE_HISTORY_APP_GROUP)"]
    )
    assert (
        app["keychain-access-groups"]
        == share["keychain-access-groups"]
        == ["$(PHONE_HISTORY_KEYCHAIN_GROUP)"]
    )
    assert "com.apple.developer.family-controls" not in app
    assert "com.apple.developer.networking.networkextension" not in app


def test_share_extension_is_queue_only_and_adot_is_user_declared() -> None:
    source = (ROOT / "ios/ShareExtension/ShareViewController.swift").read_text(encoding="utf-8")
    assert "markAsADotCallRecording" in source
    assert "isLikelyAudio" in source
    assert "URLSession" not in source
    assert "filename.contains" not in source


def test_privacy_manifests_declare_explicit_user_content_without_tracking() -> None:
    expected = {
        "NSPrivacyCollectedDataTypeOtherUserContent",
        "NSPrivacyCollectedDataTypePhotosorVideos",
        "NSPrivacyCollectedDataTypeAudioData",
        "NSPrivacyCollectedDataTypeBrowsingHistory",
        "NSPrivacyCollectedDataTypeDeviceID",
    }
    for relative in (
        "ios/App/PrivacyInfo.xcprivacy",
        "ios/ShareExtension/PrivacyInfo.xcprivacy",
    ):
        manifest = plistlib.loads((ROOT / relative).read_bytes())
        assert manifest["NSPrivacyTracking"] is False
        collected = manifest["NSPrivacyCollectedDataTypes"]
        assert {item["NSPrivacyCollectedDataType"] for item in collected} == expected
        assert all(item["NSPrivacyCollectedDataTypeTracking"] is False for item in collected)
        assert all(
            item["NSPrivacyCollectedDataTypePurposes"]
            == ["NSPrivacyCollectedDataTypePurposeAppFunctionality"]
            for item in collected
        )
        defaults = next(
            item
            for item in manifest["NSPrivacyAccessedAPITypes"]
            if item["NSPrivacyAccessedAPIType"] == "NSPrivacyAccessedAPICategoryUserDefaults"
        )
        assert defaults["NSPrivacyAccessedAPITypeReasons"] == ["1C8F.1"]
