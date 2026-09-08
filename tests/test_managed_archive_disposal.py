from __future__ import annotations

import gzip
import io
import os
import tarfile
import zlib
from pathlib import Path

import pytest

from sb.erasure import purge_matching_managed_copies, scan_managed_surfaces
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.provider_surface_files import scan_file_surface
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_specs import PROVIDER_SURFACE_SPECS

NEEDLE = b"compressed-backup-sensitive-canary"


def tar_bytes(name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo(name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


@pytest.mark.parametrize("kind", ["gzip", "tar", "tar-gzip", "git-object", "nested-gzip"])
def test_decoded_copies_are_detected_and_durably_disposed(tmp_path: Path, kind: str):
    if kind == "gzip":
        body = gzip.compress(NEEDLE)
    elif kind == "tar":
        body = tar_bytes("vault/wiki/page.md", NEEDLE)
    elif kind == "git-object":
        body = gzip.compress(tar_bytes("vault/.git/objects/aa/" + "b" * 38,
            zlib.compress(b"blob " + str(len(NEEDLE)).encode() + b"\0" + NEEDLE)))
    elif kind == "nested-gzip":
        body = gzip.compress(tar_bytes("vault/raw/nested.gz", gzip.compress(NEEDLE)))
    else:
        body = gzip.compress(tar_bytes("vault/wiki/page.md", NEEDLE))
    archive = tmp_path / "backup-artifact"
    archive.write_bytes(body)
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text("checksum metadata")
    unrelated = tmp_path / "unrelated.gz"
    unrelated.write_bytes(gzip.compress(b"unrelated data"))
    before = scan_managed_surfaces((tmp_path,), (NEEDLE,))
    assert before.matches > 0 and before.scan_errors == 0
    assert purge_matching_managed_copies((tmp_path,), (NEEDLE,)) == 2
    assert not archive.exists() and not sidecar.exists() and unrelated.exists()
    after = scan_managed_surfaces((tmp_path,), (NEEDLE,))
    assert after.matches == 0 and after.scan_errors == 0


@pytest.mark.parametrize("body", [
    b"\x1f\x8btruncated", gzip.compress(NEEDLE)[:-2], b"PK\x03\x04unsupported",
    gzip.compress(tar_bytes("vault/.git/objects/pack/source.pack", b"PACKdata")),
    gzip.compress(NEEDLE) + gzip.compress(b"second member"),
])
def test_uninspected_archive_cannot_be_reported_as_absent(tmp_path: Path, body: bytes):
    archive = tmp_path / "archive"
    archive.write_bytes(body)
    ordinary = tmp_path / "ordinary"
    ordinary.write_bytes(NEEDLE)
    scan = scan_managed_surfaces((tmp_path,), (NEEDLE,))
    assert scan.scan_errors > 0
    with pytest.raises(ManagedInspectionError):
        purge_matching_managed_copies((tmp_path,), (NEEDLE,))
    assert ordinary.exists() and archive.exists()  # Preflight all files before any removal.


def test_decode_budget_and_chunk_boundary(tmp_path: Path, monkeypatch):
    archive = tmp_path / "copy.gz"
    archive.write_bytes(gzip.compress(b"x" * 65_530 + NEEDLE + b"y" * 100_000))
    assert inspect_managed_file(archive, (NEEDLE,)).matches > 0
    monkeypatch.setattr("sb.managed_file_inspection.MAX_DECODED_BYTES", 1024)
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_BUDGET"):
        purge_matching_managed_copies((tmp_path,), (NEEDLE,))
    assert archive.exists()


def test_partial_sidecar_disposal_remains_resumable(tmp_path: Path, monkeypatch):
    archive = tmp_path / "backup.gz"
    archive.write_bytes(gzip.compress(NEEDLE))
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text("checksum")
    real_unlink = os.unlink

    def interrupted(path, *, dir_fd=None):
        real_unlink(path, dir_fd=dir_fd)
        raise KeyboardInterrupt()

    with monkeypatch.context() as context:
        context.setattr(os, "unlink", interrupted)
        with pytest.raises(KeyboardInterrupt):
            purge_matching_managed_copies((tmp_path,), (NEEDLE,))
    assert archive.exists() and not sidecar.exists()
    assert purge_matching_managed_copies((tmp_path,), (NEEDLE,)) == 1
    assert not archive.exists()


def test_fixed_provider_backup_surface_decodes_and_reports_errors(tmp_path: Path):
    layout = ProviderSurfaceLayout(tmp_path, tmp_path, tmp_path, tmp_path,
        tmp_path, tmp_path, tmp_path, tmp_path)
    spec = next(value for value in PROVIDER_SURFACE_SPECS if value.definition.surface_id == "managed_backups")
    archive = tmp_path / "backup.gz"
    archive.write_bytes(gzip.compress(NEEDLE))
    observed = scan_file_surface(layout, spec, (NEEDLE,))
    assert observed.match_count > 0 and observed.error_count == 0
    archive.write_bytes(b"\x1f\x8btruncated")
    observed = scan_file_surface(layout, spec, (NEEDLE,))
    assert observed.error_count > 0
