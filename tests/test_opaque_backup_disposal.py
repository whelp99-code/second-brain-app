"""Opaque members can only be disposed, never certified as absent."""
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sb.effect_values import is_json_object, strict_loads
from sb.managed_backup_manifest import validate_backup_archive
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.ops import create_backup
from sb.store.cas import ContentAddressedStore
from tests.test_ops import _seed_vault


def test_invalid_outer_container_raises_without_unlinking(tmp_path: Path) -> None:
    # Given: a tar.gz name whose bytes are not a canonical product backup, plus a match.
    backups = tmp_path / "backups"
    backups.mkdir()
    archive = backups / "not-a-backup.tar.gz"
    _ = archive.write_bytes(b"PK\x03\x04 damaged outer container")
    matching = backups / "matching"
    _ = matching.write_bytes(b"independent-match")
    before = {path.name: path.read_bytes() for path in backups.iterdir()}
    # When: inspection fails and the container cannot validate for disposal.
    with pytest.raises(ManagedInspectionError):
        _ = purge_matching_managed_copies((backups,), (b"independent-match",))
    # Then: neither the invalid container nor the independent match is unlinked.
    assert {path.name: path.read_bytes() for path in backups.iterdir()} == before


def test_legacy_originless_backup_can_be_disposed_not_retained(tmp_path: Path) -> None:
    root, _ = _seed_vault(tmp_path)
    _ = ContentAddressedStore(root).put(b"PK\x03\x04 damaged document")
    original = tmp_path / "original.tar.gz"
    _ = create_backup(root, original)
    backups = tmp_path / "backups"
    backups.mkdir()
    archive = backups / "legacy.tar.gz"
    with tarfile.open(original) as source, tarfile.open(archive, "w:gz") as target:
        for member in source:
            stream = source.extractfile(member)
            assert stream is not None
            payload = stream.read()
            if member.name == "manifest.json":
                loaded = strict_loads(payload, len(payload))
                assert is_json_object(loaded)
                del loaded["origin"]
                payload = json.dumps(loaded).encode()
                member.size = len(payload)
            target.addfile(member, io.BytesIO(payload))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    _ = archive.with_name(archive.name + ".sha256").write_text(f"{checksum}  {archive.name}\n")
    with pytest.raises(ManagedInspectionError):
        _ = validate_backup_archive(archive)
    assert purge_matching_managed_copies((backups,), (b"unseen",)) == 2


@pytest.mark.parametrize("corrupt_checksum", [False, True])
def test_opaque_raw_in_canonical_backup_is_conservatively_disposed(
    tmp_path: Path, corrupt_checksum: bool,
) -> None:
    root, _ = _seed_vault(tmp_path)
    # Production contains UTF-8 replacement-decoded Office input: PK magic,
    # but no valid ZIP central directory. It cannot prove content absence.
    _ = ContentAddressedStore(root).put(b"PK\x03\x04\xef\xbf\xbd damaged document")
    backups = tmp_path / "backups"
    archive = backups / "copy.tar.gz"
    _ = create_backup(root, archive)
    with pytest.raises(ManagedInspectionError):
        _ = inspect_managed_file(archive, (b"unseen-canary",))
    if corrupt_checksum:
        _ = archive.with_name(archive.name + ".sha256").write_text("forged")
        with pytest.raises(ManagedInspectionError):
            _ = purge_matching_managed_copies((backups,), (b"unseen-canary",))
        assert archive.exists()
    else:
        assert purge_matching_managed_copies((backups,), (b"unseen-canary",)) == 2
        assert not archive.exists()


def test_opaque_disposal_resumes_after_checksum_unlink(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root, _ = _seed_vault(tmp_path)
    _ = ContentAddressedStore(root).put(b"PK\x03\x04 damaged document")
    backups = tmp_path / "backups"
    archive = backups / "copy.tar.gz"
    _ = create_backup(root, archive)
    unlink = os.unlink
    def interrupted(path: str | bytes | os.PathLike[str], *, dir_fd: int | None = None) -> None:
        unlink(path, dir_fd=dir_fd)
        raise KeyboardInterrupt
    with monkeypatch.context() as context:
        context.setattr(os, "unlink", interrupted)
        with pytest.raises(KeyboardInterrupt):
            _ = purge_matching_managed_copies((backups,), (b"unseen",))
    assert archive.exists()
    assert purge_matching_managed_copies((backups,), (b"unseen",)) == 1
    assert not archive.exists()
