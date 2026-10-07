"""Backup bytes, paths and roundtrip contracts."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from sb.ops import BACKUP_FORMAT, OperationError, create_backup, restore_backup
from sb.search import SearchIndex
from sb.store.ledger import CURRENT_SCHEMA_VERSION, ledger_schema_version
from tests.ops_fixture import TERM, seed_vault


def test_backup_restore_roundtrip_preserves_unicode_git_cas_and_search(tmp_path: Path) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backups" / "second-brain.tar.gz"

    backup = create_backup(root, archive)
    restored = restore_backup(archive, tmp_path / "복원-vault")

    assert backup.archive == archive.resolve()
    assert len(backup.checksum) == 64
    assert archive.with_name(f"{archive.name}.sha256").is_file()
    assert restored.files == backup.files
    assert restored.bytes == backup.bytes
    assert (restored.destination / ".git").is_dir()
    assert (restored.destination / "wiki" / "계약-일정.md").is_file()
    assert (
        ledger_schema_version(restored.destination / ".sb" / "ledger.db") == CURRENT_SCHEMA_VERSION
    )
    assert SearchIndex(restored.destination).search(TERM)
    raw_files = [path for path in (restored.destination / "raw").rglob("*") if path.is_file()]
    assert len(raw_files) == 1
    assert hashlib.sha256(raw_files[0].read_bytes()).hexdigest() == raw_files[0].name



def test_corrupted_backup_sidecar_refuses_restore_without_mutation(tmp_path: Path) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    with archive.open("ab") as handle:
        _ = handle.write(b"tamper")
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    _ = sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(OperationError, match="checksum mismatch"):
        _ = restore_backup(archive, destination, force=True)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"



def test_restore_rejects_path_traversal_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.tar.gz"
    manifest = {
        "format": BACKUP_FORMAT,
        "files": [
            {
                "path": "../escape",
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "size": 1,
                "mode": 0o600,
            }
        ],
    }
    payload = json.dumps(manifest).encode()
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
        member = tarfile.TarInfo("vault/../escape")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(OperationError, match="unsafe backup path"):
        _ = restore_backup(archive, tmp_path / "restored")

    assert not (tmp_path / "escape").exists()



def test_restore_nonempty_destination_requires_force_and_preserves_previous(tmp_path: Path) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    _ = (destination / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(OperationError, match="not empty"):
        _ = restore_backup(archive, destination)

    result = restore_backup(archive, destination, force=True)
    assert result.previous is not None
    assert (result.previous / "old.txt").read_text(encoding="utf-8") == "old"
    assert (destination / "wiki" / "계약-일정.md").is_file()
