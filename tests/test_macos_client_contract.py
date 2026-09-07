"""Static cross-platform gates for the native macOS client source contract.

The Ubuntu worker cannot compile AppKit/SwiftUI, so these tests protect the
server/client protocol and the mandatory macOS integration surfaces. The real
Xcode build and UI runtime remain a separate release gate.
"""

from __future__ import annotations

import os
import plistlib
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "clients" / "macos" / "SecondBrainMac"
CORE = MAC / "Sources" / "SecondBrainCore"
APP = MAC / "Sources" / "SecondBrainMac"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_native_client_package_has_core_app_and_tests() -> None:
    manifest = _text(MAC / "Package.swift")
    assert '.macOS(.v14)' in manifest
    assert 'name: "SecondBrainCore"' in manifest
    assert 'name: "SecondBrainMac"' in manifest
    assert 'name: "SecondBrainCoreTests"' in manifest
    assert (CORE / "APIClient.swift").is_file()
    assert (CORE / "FolderSync.swift").is_file()
    assert (APP / "SecondBrainMacApp.swift").is_file()


def test_six_mandatory_mac_capabilities_are_present() -> None:
    ui = _text(APP / "SecondBrainMacApp.swift")
    model = _text(APP / "AppModel.swift")
    services = _text(APP / "SystemServices.swift")
    settings = _text(APP / "AppSettings.swift")
    combined = f"{ui}\n{model}\n{services}\n{settings}"

    required_symbols = {
        "native menu bar": "MenuBarExtra",
        "drag and drop": ".dropDestination(for: URL.self)",
        "folder picker": "NSOpenPanel",
        "folder watcher": "DispatchSource.makeFileSystemObjectSource",
        "notification center": "UNUserNotificationCenter",
        "launch at login": "SMAppService.mainApp",
        "immediate run": "runNow()",
    }
    missing = [name for name, symbol in required_symbols.items() if symbol not in combined]
    assert missing == []


def test_mac_api_paths_match_server_paths() -> None:
    client = _text(CORE / "APIClient.swift")
    server = _text(ROOT / "sb" / "web.py")
    for path in (
        "/api/uploads",
        "/api/run",
        "/api/status",
        "/api/search",
        "/api/briefing/latest",
        "/api/capabilities",
    ):
        assert path in client
        assert path in server


def test_folder_sync_is_one_way_manifest_based_and_bounded() -> None:
    core = _text(CORE / "FolderSync.swift")
    model = _text(APP / "AppModel.swift")
    assert "SyncManifest" in core
    assert "isSymbolicLink" in core
    assert "resolvingSymlinksInPath" in core
    assert "SHA256.hash(data: keyMaterial)" in core
    assert '"\\(folderID.uuidString)/\\(relativePath)"' not in core
    assert "skipsHiddenFiles" in core
    assert "maxUploadBytes" in core
    assert "manifest.record" in model
    assert "client().upload" in model or "api.upload" in model
    assert "removeItem(at: candidate.fileURL)" not in model
    assert "write(to: candidate.fileURL)" not in model


def test_notification_briefings_are_opt_in_for_lock_screen_privacy() -> None:
    settings = _text(APP / "AppSettings.swift")
    assert "var notificationBriefings = false" in settings


def test_folder_bookmarks_support_sandboxed_and_regular_local_builds() -> None:
    settings = _text(APP / "AppSettings.swift")
    assert "options: [.withSecurityScope]" in settings
    assert "options: []" in settings


def test_api_token_uses_keychain_and_ssh_avoids_shell() -> None:
    settings = _text(APP / "AppSettings.swift")
    services = _text(APP / "SystemServices.swift")
    assert "SecItemAdd" in settings
    assert "SecItemCopyMatching" in settings
    assert 'forKey: "api-token"' not in settings
    assert 'URL(fileURLWithPath: "/usr/bin/ssh")' in services
    assert "task.arguments" in services
    assert "/bin/sh" not in services
    assert "Process()" in services


def test_native_upload_sends_content_digest_for_end_to_end_integrity() -> None:
    client = _text(CORE / "APIClient.swift")
    assert "import CryptoKit" in client
    assert "SHA256.hash(data: data)" in client
    assert 'case contentSHA256 = "content_sha256"' in client


def test_app_bundle_is_menu_bar_native_and_build_scripts_are_executable() -> None:
    with (MAC / "Resources" / "Info.plist").open("rb") as handle:
        info = cast(dict[str, object], plistlib.load(handle))
    assert info["CFBundlePackageType"] == "APPL"
    assert info["CFBundleIdentifier"] == "kr.baeruro.secondbrain.mac"
    assert info["LSUIElement"] is True
    assert info["LSMinimumSystemVersion"] == "14.0"
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = cast(dict[str, object], tomllib.load(handle)["project"])
    assert info["CFBundleShortVersionString"] == project["version"]

    for script in (MAC / "Scripts" / "build-app.sh", MAC / "Scripts" / "install-app.sh"):
        assert script.is_file()
        assert os.stat(script).st_mode & 0o111


def test_mcp_exposes_explicit_immediate_run_tool() -> None:
    mcp = _text(ROOT / "sb" / "mcp.py")
    assert '"sb_run"' in mcp
    assert 'server.tool(name="sb_run")(sb_run)' in mcp
    assert "run_all(runtime_config, runtime_config.configured_source_ids)" in mcp
    assert "already_running" in mcp


def test_ubuntu_installer_enables_loopback_web_service_for_mac_client() -> None:
    service = _text(ROOT / "deploy" / "systemd" / "second-brain-web.service")
    installer_path = ROOT / "deploy" / "install-systemd-user.sh"
    installer = _text(installer_path)
    assert "sb web --host 127.0.0.1 --port 8765" in service
    assert "Restart=on-failure" in service
    assert "EnvironmentFile=-%h/.config/second-brain/environment" in service
    for incompatible in (
        "ProtectControlGroups=true",
        "ProtectKernelModules=true",
        "ProtectKernelTunables=true",
    ):
        assert incompatible not in service
    assert "second-brain-web.service" in installer
    assert "enable --now second-brain-web.service" in installer
    assert os.stat(installer_path).st_mode & 0o111


def test_mac_client_imports_core_models_and_uses_dedicated_local_tunnel_port() -> None:
    settings = _text(APP / "AppSettings.swift")
    services = _text(APP / "SystemServices.swift")
    ui = _text(APP / "SecondBrainMacApp.swift")
    assert 'import SecondBrainCore' in services
    assert 'serverURL = "http://127.0.0.1:18765"' in settings
    assert 'localPort = 18765' in settings
    assert 'remotePort = 8765' in settings
    assert 'Color.secondary' in ui and 'Color.red' in ui
