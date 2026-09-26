"""The publication lock preserves domain errors and releases on every exit."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sb.life_lock import VaultPublicationBusy, publication_lock
from sb.uploads import UploadRejected


@pytest.mark.parametrize(
    "error", [UploadRejected("relative_path escapes inbox"), ValueError("bad")]
)
def test_original_exception_survives_and_lock_is_released(tmp_path: Path, error: Exception) -> None:
    root = tmp_path / "vault"
    with pytest.raises(type(error)) as caught, publication_lock(root):
        raise error
    assert caught.value is error
    assert not isinstance(caught.value, FrozenInstanceError)
    with publication_lock(root):
        pass


def test_exclusion_and_persistent_lock_identity(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    with (
        publication_lock(root),
        pytest.raises(VaultPublicationBusy, match="BUSY"),
        publication_lock(root),
    ):
        pytest.fail("concurrent publication must not acquire the lock")
    lock = next(tmp_path.glob(".sb-restore-*.lock"))
    inode = lock.stat().st_ino
    with publication_lock(root):
        assert lock.stat().st_ino == inode
    assert lock.exists()
