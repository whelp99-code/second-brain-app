"""Atomic restore publication and rollback preserve prior vaults."""

from __future__ import annotations

from datetime import tzinfo
from pathlib import Path
from typing import override

import pytest

from sb.ops import OperationError, create_backup, restore_backup
from tests.ops_fixture import seed_vault


def test_restore_same_timestamp_preserves_each_previous_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    class FixedDatetime(datetime):
        @classmethod
        @override
        def now(cls, tz: tzinfo | None = None) -> datetime:
            del tz
            return cls(2026, 9, 9, tzinfo=UTC)

    monkeypatch.setattr("sb.ops_restore.datetime", FixedDatetime)
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    _ = (destination / "original.txt").write_text("first memory")
    first = restore_backup(archive, destination, force=True)
    _ = (destination / "second.txt").write_text("second memory")
    second = restore_backup(archive, destination, force=True)
    assert first.previous is not None and second.previous is not None
    assert first.previous != second.previous
    assert (first.previous / "original.txt").read_text() == "first memory"
    assert (second.previous / "second.txt").read_text() == "second memory"
    assert (destination / "wiki" / "계약-일정.md").is_file()



def test_restore_publish_failure_preserves_empty_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir(mode=0o700)
    original_stat = destination.stat()
    import os
    original_replace = os.replace

    def fail_publish(source: Path, target: Path) -> None:
        if Path(source).name.startswith(".existing.restore-"):
            raise OSError("injected publish failure")
        return original_replace(source, target)

    monkeypatch.setattr("sb.ops_restore.os.replace", fail_publish)
    with pytest.raises(OSError, match="injected publish failure"):
        _ = restore_backup(archive, destination)
    assert destination.is_dir()
    assert destination.stat().st_ino == original_stat.st_ino
    assert destination.stat().st_mode == original_stat.st_mode
    assert not list(destination.iterdir())
    assert not list(tmp_path.glob(".existing.restore-*"))



def test_restore_atomically_replaces_empty_destination(tmp_path: Path) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    result = restore_backup(archive, destination)
    assert result.previous is None
    assert (destination / "wiki" / "계약-일정.md").is_file()



def test_restore_publish_failure_recovers_previous_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    _ = (destination / "original.txt").write_text("original memory")
    import os
    original_replace = os.replace

    def fail_publish(source: Path, target: Path) -> None:
        if Path(source).name.startswith(".existing.restore-"):
            raise OSError("injected publish failure")
        return original_replace(source, target)

    monkeypatch.setattr("sb.ops_restore.os.replace", fail_publish)
    with pytest.raises(OSError, match="injected publish failure"):
        _ = restore_backup(archive, destination, force=True)
    assert (destination / "original.txt").read_text() == "original memory"
    assert not list(tmp_path.glob(".existing.restore-*"))



@pytest.mark.parametrize("new_occupant", [False, True])
def test_restore_failed_rollback_preserves_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_occupant: bool) -> None:
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    _ = (destination / "original.txt").write_text("original memory")
    import os
    original_replace = os.replace

    def fail_publish_and_rollback(source: Path, target: Path) -> None:
        if Path(source).name.startswith(".existing.restore-"):
            if new_occupant:
                destination.mkdir()
                _ = (destination / "new.txt").write_text("concurrent content")
            raise OSError("publish failure")
        if Path(source).name.startswith("existing.pre-restore-"):
            raise OSError("rollback failure")
        return original_replace(source, target)

    monkeypatch.setattr("sb.ops_restore.os.replace", fail_publish_and_rollback)
    with pytest.raises(OperationError, match="RESTORE_ROLLBACK_FAILED") as error:
        _ = restore_backup(archive, destination, force=True)
    previous = next(tmp_path.glob("existing.pre-restore-*"))
    assert str(previous) in str(error.value)
    assert (previous / "original.txt").read_text() == "original memory"
    if new_occupant:
        assert (destination / "new.txt").read_text() == "concurrent content"



def test_restore_never_deletes_preexisting_staging(tmp_path: Path) -> None:
    import os
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "restored"
    existing = tmp_path / f".restored.restore-{os.getpid()}"
    existing.mkdir()
    _ = (existing / "recovery-evidence.txt").write_text("other operation")
    _ = restore_backup(archive, destination)
    assert (existing / "recovery-evidence.txt").read_text() == "other operation"
    assert (destination / "wiki" / "계약-일정.md").is_file()
