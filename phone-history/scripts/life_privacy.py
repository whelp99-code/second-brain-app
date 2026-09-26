"""Static constraints for the optional, read-only Life HealthKit integration.

This is not a native build or device acceptance test. In particular, it cannot
prove that HealthKit read permission was granted or that background sync ran.
"""

from __future__ import annotations

import plistlib
from pathlib import Path


def health_boundary_errors(ios: Path) -> list[str]:
    errors: list[str] = []
    app = plistlib.loads((ios / "App/PhoneHistory.entitlements").read_bytes())
    share = plistlib.loads((ios / "ShareExtension/PhoneHistoryShare.entitlements").read_bytes())
    info = plistlib.loads((ios / "App/Info.plist").read_bytes())
    share_info = plistlib.loads((ios / "ShareExtension/Info.plist").read_bytes())
    common = {"com.apple.security.application-groups", "keychain-access-groups"}
    if set(app) != common | {"com.apple.developer.healthkit"}:
        errors.append("app_entitlement_scope")
    if app.get("com.apple.developer.healthkit") is not True:
        errors.append("health_capability_missing")
    if set(share) != common:
        errors.append("share_entitlement_scope")
    usage = {key for key in info if key.endswith("UsageDescription")}
    if usage != {"NSHealthShareUsageDescription"} or not info.get("NSHealthShareUsageDescription"):
        errors.append("read_only_health_usage")
    if any(key.endswith("UsageDescription") for key in share_info):
        errors.append("share_runtime_permission")
    health = (ios / "App/LifeHealthBridge.swift").read_text()
    if "requestAuthorization(toShare: [], read: types)" not in health:
        errors.append("health_read_only_authorization")
    if 'stringArray(forKey: "sb.health.selected") ?? []' not in health:
        errors.append("health_selection_default_off")
    if 'bool(forKey: "sb.health.foreground")' not in health:
        errors.append("health_foreground_default_off")
    if (
        "for kind in selected.sorted()" not in health
        or "guard selected.contains(kind)" not in health
    ):
        errors.append("health_selected_types_only")
    if "AES.GCM.seal" not in health or "AES.GCM.open" not in health:
        errors.append("health_queue_not_encrypted")
    spec = (ios / "project.yml").read_text()
    share_target = spec.split("  PhoneHistoryShare:", 1)[1].split("  PhoneHistoryTests:", 1)[0]
    if "Core/GeneratedContract.swift" not in share_target:
        errors.append("share_generated_contract_missing")
    if any(
        path in share_target
        for path in (
            "Core/LifeMemoryBridge.swift",
            "Core/SyncService.swift",
            "Core/APIClient.swift",
            "- path: App\n",
        )
    ):
        errors.append("share_network_or_health_source")
    return errors
