"""Adversarial ZIP framing and shared resource-accounting regressions."""

from __future__ import annotations

import gzip
import stat
from pathlib import Path
from typing import Final

import pytest
from pytest import MonkeyPatch

from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from tests.managed_archive_fixtures import OTHER, SENTINEL, document, zipped
from tests.test_managed_archive_disposal import tar_bytes

_GOOD: Final = document(SENTINEL)
_CENTRAL: Final = _GOOD.index(b"PK\x01\x02")
_END: Final = len(_GOOD) - 22


def replaced(raw: bytes, offset: int, value: bytes) -> bytes:
    return raw[:offset] + value + raw[offset + len(value):]


@pytest.mark.parametrize("body", [
    pytest.param(_GOOD[:_CENTRAL], id="missing-central-directory"),
    pytest.param(zipped("safe", OTHER, extra=b"x"), id="truncated-extra-field"),
    pytest.param(replaced(_GOOD, 4, b"\x2d\0"), id="local-version-mismatch"),
    pytest.param(replaced(_GOOD, _END + 16, b"\xff" * 4), id="zip64-offset"),
    pytest.param(replaced(_GOOD, 14, b"\xff" * 4), id="local-crc-mismatch"),
    pytest.param(replaced(_GOOD, _CENTRAL + 16, b"\xff" * 4), id="central-crc-mismatch"),
    pytest.param(replaced(_GOOD, _CENTRAL + 42, b"\x01\0\0\0"), id="local-offset-mismatch"),
    pytest.param(replaced(_GOOD, 30, b"!"), id="filename-mismatch"),
    pytest.param(replaced(_GOOD, 6, b"\x01\0"), id="encrypted-local-member"),
    pytest.param(replaced(_GOOD, _CENTRAL + 8, b"\x01\0"), id="encrypted-central-member"),
    pytest.param(replaced(_GOOD, _CENTRAL + 8, b"\x08\0"), id="data-descriptor"),
    pytest.param(replaced(_GOOD, _CENTRAL + 10, b"\x0c\0"), id="unsupported-codec"),
    pytest.param(replaced(_GOOD, _END + 4, b"\x01\0"), id="multi-disk"),
    pytest.param(replaced(_GOOD, _END + 8, b"\xff" * 4), id="zip64-count"),
    pytest.param(replaced(_GOOD, _CENTRAL + 38,
                          (stat.S_IFLNK << 16).to_bytes(4, "little")), id="symlink"),
    pytest.param(_GOOD[:_CENTRAL] + b"gap" + _GOOD[_CENTRAL:], id="unaccounted-gap"),
    pytest.param(replaced(_GOOD, _END + 10, b"\x01\0"), id="inventory-count-mismatch"),
    pytest.param(zipped("nested.docx", _GOOD[:_CENTRAL]), id="nested-missing-central"),
    pytest.param(zipped("./alias", OTHER), id="noncanonical-path"),
    pytest.param(zipped("a\\..\\escape", OTHER), id="windows-path-escape"),
])
def test_ambiguous_member_inventory_cannot_certify_absence(tmp_path: Path, body: bytes) -> None:
    # Given: malformed bytes after an independently matching physical copy.
    archive = tmp_path / "nested.zip"
    _ = archive.write_bytes(body)
    matching = tmp_path / "matching"
    _ = matching.write_bytes(SENTINEL)
    # When / Then: no match shortcut bypasses complete validation.
    with pytest.raises(ManagedInspectionError):
        _ = purge_matching_managed_copies((tmp_path,), (SENTINEL,))
    assert archive.read_bytes() == body and matching.read_bytes() == SENTINEL


@pytest.mark.parametrize("constant", ["MAX_ZIP_BYTES", "MAX_MEMBER_BYTES", "MAX_RATIO"])
def test_zip_limits_are_enforced_before_allocation(
    tmp_path: Path, monkeypatch: MonkeyPatch, constant: str,
) -> None:
    # Given: a small valid member exceeding a deliberately reduced named budget.
    archive = tmp_path / "nested.zip"
    _ = archive.write_bytes(_GOOD)
    monkeypatch.setattr("sb.managed_zip." + constant, 1)
    # When / Then: refusal is an explicit budget result, never a clean scan.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_BUDGET"):
        _ = inspect_managed_file(archive, (OTHER,))


@pytest.mark.parametrize("constant", ["MAX_DECODED_BYTES", "MAX_MEMBERS", "MAX_DEPTH"])
def test_shared_budget_applies_across_nested_members(
    tmp_path: Path, monkeypatch: MonkeyPatch, constant: str,
) -> None:
    # Given: nested valid containers sharing one accounting context.
    archive = tmp_path / "nested.zip"
    _ = archive.write_bytes(zipped("nested.docx", _GOOD))
    monkeypatch.setattr("sb.managed_file_inspection." + constant, 0)
    # When / Then: nested branches cannot obtain fresh budgets.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_BUDGET"):
        _ = inspect_managed_file(archive, (OTHER,))


@pytest.mark.parametrize("tail", [b"unparsed-data", tar_bytes("hidden", SENTINEL)])
def test_tar_end_marker_cannot_hide_additional_member_bytes(tmp_path: Path, tail: bytes) -> None:
    # Given: valid gzip framing but content hidden after an earlier tar end marker.
    archive = tmp_path / "copy.tar.gz"
    _ = archive.write_bytes(gzip.compress(tar_bytes("clean.docx", document(OTHER)) + tail))
    # When / Then: tarfile read-ahead and end-of-archive cannot silently discard bytes.
    with pytest.raises(ManagedInspectionError):
        _ = inspect_managed_file(archive, (SENTINEL,))
