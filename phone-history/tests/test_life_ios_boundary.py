"""Negative controls for Life's narrowly scoped iOS integration."""

from __future__ import annotations

import plistlib
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
health_boundary_errors = runpy.run_path(str(ROOT / "scripts/life_privacy.py"))[
    "health_boundary_errors"
]


@pytest.fixture
def ios(tmp_path: Path) -> Path:
    result = tmp_path / "ios"
    for relative in (
        "App/PhoneHistory.entitlements",
        "ShareExtension/PhoneHistoryShare.entitlements",
        "App/Info.plist",
        "ShareExtension/Info.plist",
        "App/LifeHealthBridge.swift",
        "project.yml",
    ):
        target = result / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "ios" / relative, target)
    return result


def test_shipping_health_boundary(ios: Path) -> None:
    assert health_boundary_errors(ios) == []


@pytest.mark.parametrize(
    "relative, key, value, expected",
    [
        (
            "ShareExtension/PhoneHistoryShare.entitlements",
            "com.apple.developer.healthkit",
            True,
            "share_entitlement_scope",
        ),
        (
            "App/PhoneHistory.entitlements",
            "com.apple.developer.networking.networkextension",
            [],
            "app_entitlement_scope",
        ),
        (
            "App/Info.plist",
            "NSHealthUpdateUsageDescription",
            "write health",
            "read_only_health_usage",
        ),
        ("App/Info.plist", "NSCameraUsageDescription", "camera", "read_only_health_usage"),
    ],
)
def test_forbidden_permission_is_rejected(
    ios: Path, relative: str, key: str, value: object, expected: str
) -> None:
    path = ios / relative
    data = plistlib.loads(path.read_bytes())
    data[key] = value
    path.write_bytes(plistlib.dumps(data))
    assert expected in health_boundary_errors(ios)


def test_health_write_request_is_rejected(ios: Path) -> None:
    path = ios / "App/LifeHealthBridge.swift"
    path.write_text(path.read_text().replace("toShare: []", "toShare: types"))
    assert "health_read_only_authorization" in health_boundary_errors(ios)


def test_missing_share_contract_is_rejected(ios: Path) -> None:
    path = ios / "project.yml"
    path.write_text(path.read_text().replace("      - path: Core/GeneratedContract.swift\n", ""))
    assert "share_generated_contract_missing" in health_boundary_errors(ios)


def test_event_device_identity_matches_schema() -> None:
    import json

    schema = json.loads((ROOT / "contracts/phone-event-v1.schema.json").read_text())
    assert "device_id" in schema["properties"]
    assert "device_id" not in schema["$defs"]["event"]["properties"]
    source = (ROOT / "ios/Core/PhoneEvent.swift").read_text()
    assert 'ContractJSON.set("device_id", deviceID, in: &event, required: true)' not in source
    assert "Set(records.map(\\.deviceID)).count == 1" in source
