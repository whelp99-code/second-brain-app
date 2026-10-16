"""Unmocked directory admission preserves inode identity and private permissions."""

from __future__ import annotations

import os
import stat
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest

from sb.exports import ExportPublisher
from sb.generations import GenerationStore
from sb.request_store import RequestStore


@pytest.mark.parametrize("guard", ["generation", "export"])
def test_real_directory_keeps_inode_while_enforcing_private_mode(
    tmp_path: Path, guard: Literal["generation", "export"],
) -> None:
    root = tmp_path / "owner-directory"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    (root / "nested").mkdir(mode=0o700)
    before = root.stat(follow_symlinks=False)

    match guard:
        case "generation":
            with closing(GenerationStore(
                root, tmp_path / "share",
                provider_instance_id="btrfs-probe", provider_release_sha="a" * 40,
            )):
                pass
        case "export":
            with closing(RequestStore(tmp_path / "requests")) as requests:
                _ = ExportPublisher(root, "a" * 40, requests.exports)

    after = root.stat(follow_symlinks=False)
    assert stat.S_ISDIR(after.st_mode)
    assert after.st_uid == os.getuid()
    assert stat.S_IMODE(after.st_mode) == 0o700
    assert (after.st_dev, after.st_ino, after.st_nlink) == (
        before.st_dev, before.st_ino, before.st_nlink,
    )
