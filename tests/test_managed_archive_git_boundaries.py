"""Archived Git pack/index integrity, isolation, and recursive object inspection."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

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


_OPAQUE_GIT = (
    Damage.PACK_TRUNCATED, Damage.INDEX_TRUNCATED, Damage.PACK_CORRUPT, Damage.INDEX_CORRUPT,
    Damage.INDEX_MISSING, Damage.PACK_MISSING, Damage.ALTERNATE, Damage.NAME_MISMATCH,
)
_ADJUNCT_GIT = (Damage.BITMAP, Damage.REVERSE_INDEX)


def _damage_pack(root: Path, damage: Damage) -> None:
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
            adjunct = pack.with_suffix(".rev")
            if adjunct.exists():
                adjunct.chmod(0o600)
            _ = adjunct.write_bytes(b"unsupported-reverse-index")
        case Damage.ALTERNATE:
            _ = (root / ".git/objects/info/alternates").write_text(str(root))
        case Damage.NAME_MISMATCH:
            _ = pack.rename(folder / ("pack-" + "0" * 40 + ".pack"))
            _ = index.rename(folder / ("pack-" + "0" * 40 + ".idx"))


def _dispose_uninspected_backup(archive: Path, matching: Path) -> None:
    removed = purge_matching_managed_copies((archive.parent,), (SENTINEL,))
    retained = {path.name for path in archive.parent.iterdir()}
    assert archive.name not in retained
    assert not any(name.startswith(archive.name) for name in retained)
    assert matching.name not in retained
    assert removed >= 3
    assert purge_matching_managed_copies((archive.parent,), (SENTINEL,)) == 0


@pytest.mark.parametrize("damage", _OPAQUE_GIT)
def test_incomplete_archived_git_inventory_disposes_the_canonical_backup(
    tmp_path: Path, damage: Damage,
) -> None:
    # Given: a valid outer backup wrapping an object store that cannot be decoded.
    archive = archived(tmp_path, OTHER, packed=True)
    root = tmp_path / "source"
    _damage_pack(root, damage)
    _ = create_backup(root, archive, origin="task30-synthetic")
    ordinary = archive.parent / "matching"
    _ = ordinary.write_bytes(SENTINEL)
    # When / Then: inspection cannot certify absence, so the backup, sidecars, and
    # the independent match are disposed together. Replay finds nothing left.
    with pytest.raises(ManagedInspectionError):
        _ = inspect_managed_file(archive, (SENTINEL,))
    _dispose_uninspected_backup(archive, ordinary)


@pytest.mark.parametrize("damage", _ADJUNCT_GIT)
def test_pack_adjuncts_are_scanned_instead_of_rejecting_the_backup(
    tmp_path: Path, damage: Damage,
) -> None:
    # Given: git gc adjunct bytes sit beside a complete pack/index pair.
    archive = archived(tmp_path, OTHER, packed=True)
    root = tmp_path / "source"
    _damage_pack(root, damage)
    _ = create_backup(root, archive, origin="task30-synthetic")
    needle = b"unsupported-bitmap" if damage is Damage.BITMAP else b"unsupported-reverse-index"
    # When: the product inspector receives the canonical backup.
    result = inspect_managed_file(archive, (needle,))
    # Then: adjunct bytes are searched, and the pack itself stays inspectable.
    assert result.matches > 0
    assert inspect_managed_file(archive, (SENTINEL,)).matches == 0


@pytest.mark.parametrize("suffix", [".mtimes", ".keep", ".promisor"])
def test_additional_pack_adjuncts_are_raw_scanned(tmp_path: Path, suffix: str) -> None:
    # Given: a content-free adjunct name git may write next to a real pack.
    archive = archived(tmp_path, OTHER, packed=True)
    root = tmp_path / "source"
    pack = next((root / ".git/objects/pack").glob("*.pack"))
    pack.chmod(0o600)
    _ = pack.with_suffix(suffix).write_bytes(b"adjunct-" + SENTINEL)
    _ = create_backup(root, archive, origin="task30-synthetic")
    # When / Then: the adjunct cannot hide a sentinel or fail the object decode.
    assert inspect_managed_file(archive, (SENTINEL,)).matches > 0


def test_unknown_pack_directory_name_fails_closed(tmp_path: Path) -> None:
    # Given: a pack directory member that is neither an object file nor a known adjunct.
    archive = archived(tmp_path, OTHER, packed=True)
    root = tmp_path / "source"
    folder = root / ".git/objects/pack"
    _ = (folder / "multi-pack-index").write_bytes(b"unknown")
    _ = create_backup(root, archive, origin="task30-synthetic")
    # When / Then: an unrecognized name still cannot be skipped.
    with pytest.raises(ManagedInspectionError, match="MANAGED_ARCHIVE_UNSUPPORTED"):
        _ = inspect_managed_file(archive, (SENTINEL,))


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
