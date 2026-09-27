"""Complete nested inspection, never signature-only absence certification."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from sb.managed_backup_manifest import validate_backup_archive
from sb.managed_copy_disposal import copy_inventory
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.managed_git import inspect_git_directory
from tests.managed_archive_fixtures import OTHER, SENTINEL, archived, document, zipped


@pytest.mark.parametrize("bad_offset", [False, True])
def test_sentinel_is_detected_when_only_a_nested_compressed_member_contains_it(
    tmp_path: Path, bad_offset: bool,
) -> None:
    # Given: an outer provider backup with nested ZIP/OOXML, not plaintext sentinel bytes.
    body = zipped("nested.docx", document(SENTINEL, bad_offset=bad_offset))
    archive = archived(tmp_path, body)
    assert SENTINEL not in body and SENTINEL not in archive.read_bytes()
    # When: the shared product inspector reaches every nested member.
    result = inspect_managed_file(archive, (SENTINEL,))
    # Then: compression cannot turn a matching backup into a clean result.
    assert result.matches > 0


def test_sentinel_is_detected_when_only_an_archived_packed_object_contains_it(tmp_path: Path) -> None:
    # Given: the same object is readable in Git but is compressed inside an outer backup.
    archive = archived(tmp_path, SENTINEL, packed=True)
    assert inspect_git_directory(tmp_path / "source/.git", (SENTINEL,)).matches > 0
    assert SENTINEL not in archive.read_bytes()
    # When: the same product boundary receives the archived representation.
    result = inspect_managed_file(archive, (SENTINEL,))
    # Then: archived Git objects are included, not just physical pack bytes.
    assert result.matches > 0


@pytest.mark.parametrize("packed", [False, True])
def test_nonmatching_backup_stays_byte_identical_when_inspected_and_purged(
    tmp_path: Path, packed: bool,
) -> None:
    # Given: valid nonmatching nested content plus its content-addressed sidecar.
    archive = archived(tmp_path, OTHER if packed else document(OTHER), packed=packed)
    before = {path.name: path.read_bytes() for path in archive.parent.iterdir()}
    # When: normal validation and the real erasure decision inspect the backup.
    validate_backup_archive(archive)
    removed = purge_matching_managed_copies((archive.parent,), (SENTINEL,))
    # Then: the nonmatching backup's physical identity and inventory remain intact.
    assert removed == 0
    assert {path.name: path.read_bytes() for path in archive.parent.iterdir()} == before
    assert copy_inventory((archive.parent,), (SENTINEL,)).startswith("sha256:")


def test_bad_offset_fixture_preserves_all_local_and_central_bytes(tmp_path: Path) -> None:
    # Given: the only corruption is the EOCD central-directory start offset.
    valid = document(SENTINEL)
    damaged = document(SENTINEL, bad_offset=True)
    assert valid[:-6] == damaged[:-6] and valid[-2:] == damaged[-2:]
    with zipfile.ZipFile(io.BytesIO(damaged)) as bundle, pytest.raises(zipfile.BadZipFile):
        _ = bundle.read("word/document.xml")
    path = tmp_path / "damaged.docx"
    _ = path.write_bytes(damaged)
    # When: bounded physical record reconciliation replaces offset trust.
    result = inspect_managed_file(path, (SENTINEL,))
    # Then: inspection detects the compressed sentinel without repairing stored bytes.
    assert result.matches > 0
    assert result.digest == "sha256:" + hashlib.sha256(damaged).hexdigest()


@pytest.mark.parametrize("body", [
    b"PK\x03\x04truncated", document(SENTINEL)[:-3],
    document(SENTINEL) + b"unaccounted-tail", zipped("../escape", SENTINEL),
    zipped("/absolute", SENTINEL), zipped("safe", b"a" * 2_000_000),
    zipped("truncated.docx", document(OTHER)[:-8]),
])
def test_malformed_nested_bytes_block_all_disposal_even_after_a_positive_match(
    tmp_path: Path, body: bytes,
) -> None:
    # Given: an independently matching file and an uninspectable archive.
    archive = archived(tmp_path, body)
    ordinary = archive.parent / "matching.txt"
    _ = ordinary.write_bytes(SENTINEL)
    before = {path.name: path.read_bytes() for path in archive.parent.iterdir()}
    # When / Then: the preflight rejects the whole decision; no partial clean certification.
    with pytest.raises(ManagedInspectionError):
        _ = purge_matching_managed_copies((archive.parent,), (SENTINEL,))
    assert {path.name: path.read_bytes() for path in archive.parent.iterdir()} == before


def test_depth_budget_rejects_deeply_nested_containers(tmp_path: Path) -> None:
    # Given: finite but excessive nesting, with no reliance on recursion timing.
    body = document(OTHER)
    for _ in range(16):
        body = zipped("nested.zip", body)
    archive = archived(tmp_path, body)
    # When / Then: absence remains unproved beyond the explicit inspection depth.
    with pytest.raises(ManagedInspectionError):
        _ = copy_inventory((archive.parent,), (SENTINEL,))
