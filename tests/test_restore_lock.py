"""Restore serialization uses an inode outside the replaceable destination."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sb.ops import OperationError, create_backup, restore_backup
from sb.ops_restore import exclusive_restore
from tests.ops_fixture import seed_vault


def test_other_process_cannot_restore_locked_destination(tmp_path: Path):
    root, _config = seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    _ = (destination / "original").write_text("old memory")
    script = "from sb.ops import restore_backup; import sys; restore_backup(sys.argv[1],sys.argv[2],force=True)"
    with exclusive_restore(destination):
        done = subprocess.run(
            [sys.executable, "-c", script, str(archive), str(destination)],
            text=True, capture_output=True, timeout=20, check=False,
        )
        assert done.returncode != 0
        assert "RESTORE_DESTINATION_BUSY" in done.stderr
        assert (destination / "original").read_text() == "old memory"
        assert not list(tmp_path.glob(".destination.restore-*"))
        # Independent targets are not globally blocked.
        _ = restore_backup(archive, tmp_path / "other")
    result = restore_backup(archive, destination, force=True)
    assert result.previous is not None
    assert (result.previous / "original").read_text() == "old memory"
    assert (destination / "wiki" / "계약-일정.md").is_file()


def test_restore_lock_survives_destination_rename_and_exception(tmp_path: Path):
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(ValueError, match="abort"), exclusive_restore(destination):
        _ = destination.rename(tmp_path / "previous")
        with pytest.raises(OperationError, match="RESTORE_DESTINATION_BUSY"), exclusive_restore(destination):
            pytest.fail("second lock acquired")
        raise ValueError("abort")
    with exclusive_restore(destination):
        pass


def test_restore_refuses_hardlinked_lock(tmp_path: Path):
    destination = tmp_path / "destination"
    with exclusive_restore(destination):
        pass
    lock = next(tmp_path.glob(".sb-restore-*.lock"))
    os.link(lock, tmp_path / "alias")
    with pytest.raises(OperationError, match="RESTORE_LOCK_UNSAFE"), exclusive_restore(destination):
        pytest.fail("unsafe lock accepted")
