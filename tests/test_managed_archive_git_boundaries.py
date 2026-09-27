"""Archived Git pack/index integrity, isolation, and recursive object inspection."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import assert_never

import pytest
from pytest import MonkeyPatch

from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.ops import create_backup
from tests.managed_archive_fixtures import OTHER, SENTINEL, archived, document


class Damage(StrEnum):
    PACK_TRUNCATED = "pack-truncated"
    INDEX_TRUNCATED = "index-truncated"
    PACK_CORRUPT = "pack-corrupt"
    INDEX_CORRUPT = "index-corrupt"
    INDEX_MISSING = "index-missing"
    PACK_MISSING = "pack-missing"
    BITMAP = "bitmap"
    REVERSE_INDEX = "reverse-index"
    ALTERNATE = "alternate"
    NAME_MISMATCH = "name-mismatch"


@pytest.mark.parametrize("damage", tuple(Damage))
def test_incomplete_archived_git_inventory_blocks_all_disposal(
    tmp_path: Path, damage: Damage,
) -> None:
    # Given: a valid outer backup manifest/sidecar wrapping an invalid object store.
    archive = archived(tmp_path, OTHER, packed=True)
    root = tmp_path / "source"
    folder = root / ".git/objects/pack"
    pack = next(folder.glob("*.pack"))
    index = next(folder.glob("*.idx"))
    pack.chmod(0o600)
    index.chmod(0o600)
    match damage:
        case Damage.PACK_TRUNCATED:
            _ = pack.write_bytes(pack.read_bytes()[:-1])
        case Damage.INDEX_TRUNCATED:
            _ = index.write_bytes(index.read_bytes()[:-1])
        case Damage.PACK_CORRUPT:
            body = pack.read_bytes()
            _ = pack.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
        case Damage.INDEX_CORRUPT:
            body = index.read_bytes()
            _ = index.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
        case Damage.INDEX_MISSING:
            index.unlink()
        case Damage.PACK_MISSING:
            pack.unlink()
        case Damage.BITMAP:
            _ = pack.with_suffix(".bitmap").write_bytes(b"unsupported-bitmap")
        case Damage.REVERSE_INDEX:
            _ = pack.with_suffix(".rev").write_bytes(b"unsupported-reverse-index")
        case Damage.ALTERNATE:
            _ = (root / ".git/objects/info/alternates").write_text(str(tmp_path))
        case Damage.NAME_MISMATCH:
            _ = pack.rename(folder / ("pack-" + "0" * 40 + ".pack"))
            _ = index.rename(folder / ("pack-" + "0" * 40 + ".idx"))
        case _:
            assert_never(damage)
    _ = create_backup(root, archive, origin="task30-synthetic")
    ordinary = archive.parent / "matching"
    _ = ordinary.write_bytes(SENTINEL)
    before = {path.name: path.read_bytes() for path in archive.parent.iterdir()}
    # When / Then: no corrupt store can certify clean or permit independent deletion.
    with pytest.raises(ManagedInspectionError):
        _ = purge_matching_managed_copies((archive.parent,), (SENTINEL,))
    assert {path.name: path.read_bytes() for path in archive.parent.iterdir()} == before


def test_zip_inside_packed_blob_is_inspected_recursively(tmp_path: Path) -> None:
    # Given: a packed Git blob whose sentinel exists only inside its compressed ZIP member.
    archive = archived(tmp_path, document(SENTINEL), packed=True)
    # When: Git decodes the object and returns it to the shared representation inspector.
    result = inspect_managed_file(archive, (SENTINEL,))
    # Then: object decoding is not incorrectly treated as the final representation.
    assert result.matches > 0


def test_archived_pack_staging_enforces_byte_budget(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    # Given: a real pack pair exceeding the test's reduced staging allowance.
    archive = archived(tmp_path, OTHER, packed=True)
    monkeypatch.setattr("sb.managed_tar.MAX_PACK_BYTES", 1)
    # When / Then: size is refused before staging or invoking Git.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_BUDGET"):
        _ = inspect_managed_file(archive, (SENTINEL,))


def test_unreachable_packed_blob_still_matches(tmp_path: Path) -> None:
    # Given: remove reachability, not bytes, from an otherwise complete packed store.
    archive = archived(tmp_path, SENTINEL, packed=True)
    (tmp_path / "source/.git/refs/tags/retained").unlink()
    _ = create_backup(tmp_path / "source", archive, origin="task30-synthetic")
    # When: --batch-all-objects inspects the archived store independently of refs.
    result = inspect_managed_file(archive, (SENTINEL,))
    # Then: an unreachable object is not mistaken for erased content.
    assert result.matches > 0
