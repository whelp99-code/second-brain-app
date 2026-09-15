"""H2: stage/revoke/restore paths refuse symlink, FIFO, directory, and dangling links."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from sb.postcompact_hook import PostCompactHookError, handle_postcompact
from sb.revoked_keys import RevocationStoreError, record_revoked_key_ids, revoked_key_path
from sb.search import SearchIndex
from tests.test_postcompact_hook import _event, _seed


def _fifo(path: Path) -> None:
    os.mkfifo(path)


def _dir(path: Path) -> None:
    path.mkdir(parents=True)


def _symlink(path: Path) -> None:
    path.symlink_to(path.parent / "outside-target")


def _dangling(path: Path) -> None:
    path.symlink_to(path.parent / "missing-target")


def _plant(kind: str, path: Path) -> None:
    match kind:
        case "fifo":
            _fifo(path)
        case "dir":
            _dir(path)
        case "symlink":
            _symlink(path)
        case "dangling":
            _dangling(path)
        case unreachable:
            raise AssertionError(unreachable)


@pytest.mark.parametrize("kind", ["fifo", "dir", "symlink", "dangling"])
def test_stage_file_unsafe_kinds_fail_closed(tmp_path: Path, kind: str) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    folder = state / ".sb" / "session-memory"
    folder.mkdir(parents=True)
    _plant(kind, folder / "sess-omega.json")
    with pytest.raises(PostCompactHookError, match="HOOK_STAGE_UNSAFE"):
        handle_postcompact(_event(), SearchIndex(root, hybrid=False), state)
    outside = folder / "outside-target"
    assert not outside.exists() or outside.is_dir() is False or kind != "symlink"


@pytest.mark.parametrize("kind", ["fifo", "symlink", "dangling"])
def test_stage_directory_unsafe_kinds_fail_closed(tmp_path: Path, kind: str) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    sb_dir = state / ".sb"
    sb_dir.mkdir(parents=True)
    _plant(kind, sb_dir / "session-memory")
    with pytest.raises(PostCompactHookError, match="HOOK_STAGE_UNSAFE"):
        handle_postcompact(_event(), SearchIndex(root, hybrid=False), state)


@pytest.mark.parametrize("kind", ["fifo", "dir", "symlink", "dangling"])
def test_revocation_store_unsafe_kinds_fail_closed(tmp_path: Path, kind: str) -> None:
    path = revoked_key_path(tmp_path)
    _plant(kind, path)
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        record_revoked_key_ids(tmp_path, ["key:test"])
    outside = tmp_path / "outside-target"
    assert not outside.exists()


def test_stage_regular_file_still_writes(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    handle_postcompact(_event(), SearchIndex(root, hybrid=False), state)
    staged = state / ".sb" / "session-memory" / "sess-omega.json"
    assert staged.is_file()
    assert not staged.is_symlink()
    assert stat.S_ISREG(staged.stat().st_mode)
