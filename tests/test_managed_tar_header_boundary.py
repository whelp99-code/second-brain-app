"""Malformed consumed tar headers must never become clean backup inventories."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from sb.managed_backup_manifest import validate_backup_archive
from sb.managed_copy_disposal import copy_inventory
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.managed_surface_scan import scan_managed_surfaces
from sb.provider_surface_files import scan_file_surface
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_specs import PROVIDER_SURFACE_SPECS
from tests.managed_archive_fixtures import SENTINEL, zipped
from tests.test_managed_archive_disposal import tar_bytes


@pytest.fixture
def corrupt_backup(tmp_path: Path) -> Path:
    valid = tar_bytes("clean", b"safe")
    hidden = zipped("hidden", SENTINEL)
    assert len(hidden) < 512
    invalid = hidden.ljust(512, b"\0")
    with pytest.raises(tarfile.HeaderError):
        _ = tarfile.TarInfo.frombuf(invalid, "utf-8", "strict")
    malformed = valid[:1024] + invalid + valid[1536:]
    assert SENTINEL not in malformed
    source = tmp_path / "source"
    source.mkdir()
    _ = (source / "nested.tar").write_bytes(malformed)
    config = tmp_path / "config.toml"
    _ = config.write_text(f'vault_root = "{source}"\n')
    archive = tmp_path / "backups/z-malformed.tar.gz"
    env = dict(os.environ, SB_CONFIG=str(config), GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_CEILING_DIRECTORIES=str(tmp_path))
    _ = subprocess.run([sys.executable, "-m", "sb.cli", "backup", str(archive)],
                       env=env, check=True, capture_output=True, timeout=30)
    return archive


def test_invalid_consumed_header_cannot_return_clean_inspection(corrupt_backup: Path) -> None:
    # Given: a real CLI backup with a compressed-only sentinel in an invalid tar header.
    # When / Then: consumed invalid bytes are not treated as a zero end marker.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_INVALID"):
        _ = inspect_managed_file(corrupt_backup, (SENTINEL,))


def test_invalid_consumed_header_cannot_validate_backup(corrupt_backup: Path) -> None:
    # Given: valid outer manifest/checksum/verification do not prove nested framing valid.
    # When / Then: retained-backup validation rejects the malformed nested representation.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_INVALID"):
        _ = validate_backup_archive(corrupt_backup)


def test_invalid_consumed_header_cannot_certify_inventory(corrupt_backup: Path) -> None:
    # Given: the exact sentinel is absent from physical bytes but hidden by compression.
    # When / Then: no absence inventory is issued for the malformed container.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_INVALID"):
        _ = copy_inventory((corrupt_backup.parent,), (SENTINEL,))


def test_invalid_consumed_header_disposes_canonical_backup_without_a_clean_result(
    corrupt_backup: Path,
) -> None:
    # Given: a product backup whose nested tar header is consumed and invalid.
    matching = corrupt_backup.parent / "a-independent-match"
    _ = matching.write_bytes(SENTINEL)
    # When: inspection cannot certify the nested bytes absent.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_INVALID"):
        _ = inspect_managed_file(corrupt_backup, (SENTINEL,))
    removed = purge_matching_managed_copies((corrupt_backup.parent,), (SENTINEL,))
    retained = {path.name for path in corrupt_backup.parent.iterdir()}
    # Then: the backup, sidecars, and independent match are disposed; replay removes zero.
    assert corrupt_backup.name not in retained
    assert not any(name.startswith(corrupt_backup.name) for name in retained)
    assert matching.name not in retained
    assert removed >= 3
    assert purge_matching_managed_copies((corrupt_backup.parent,), (SENTINEL,)) == 0


def test_generic_scan_reports_invalid_consumed_header(corrupt_backup: Path) -> None:
    # Given: the malformed canonical backup is otherwise the only managed representation.
    # When: the generic scanner translates parser rejection into scan errors.
    result = scan_managed_surfaces((corrupt_backup.parent,), (SENTINEL,))
    # Then: zero raw matches cannot be confused with proved absence.
    assert result.scan_errors > 0


def test_fixed_provider_scan_reports_invalid_consumed_header(corrupt_backup: Path) -> None:
    # Given: the provider's fixed managed-backups surface points only at the synthetic root.
    root = corrupt_backup.parent
    layout = ProviderSurfaceLayout(root, root, root, root, root, root, root, root)
    spec = next(value for value in PROVIDER_SURFACE_SPECS
                if value.definition.surface_id == "managed_backups")
    # When: the provider scanner translates parser rejection into its own error count.
    result = scan_file_surface(layout, spec, (SENTINEL,))
    # Then: the fixed surface cannot certify the malformed representation clean either.
    assert result.error_count > 0


def test_valid_zero_end_headers_still_allow_clean_inspection(tmp_path: Path) -> None:
    # Given: the otherwise identical tar has genuine zero end headers, not an invalid block.
    archive = tmp_path / "valid.tar"
    _ = archive.write_bytes(tar_bytes("clean", b"safe"))
    # When: normal tar termination reaches the shared parser boundary.
    result = inspect_managed_file(archive, (SENTINEL,))
    # Then: a well-framed nonmatching tar remains supported.
    assert result.matches == 0
