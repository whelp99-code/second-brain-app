from __future__ import annotations

import os
from pathlib import Path

from pytest import MonkeyPatch

from sb.connectors.fs_safety import SafeSourceFilesystem


def test_scan_allows_directory_timestamp_churn_during_enumeration(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "inbox"
    root.mkdir(mode=0o700)
    _ = (root / "note.md").write_text("hello", encoding="utf-8")
    real_listdir = os.listdir
    touched = False

    def listdir_with_touch(fd: int) -> list[str]:
        nonlocal touched
        names = real_listdir(fd)
        if not touched:
            touched = True
            os.utime(root, None)
        return names

    monkeypatch.setattr("sb.connectors.fs_safety.os.listdir", listdir_with_touch)

    result = SafeSourceFilesystem((root,)).scan(root)

    assert [item.relative_path for item in result.files] == ["note.md"]