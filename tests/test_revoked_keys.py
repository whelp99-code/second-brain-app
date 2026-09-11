"""Durable revocation store must not drop keys or treat unsafe files as empty."""
from __future__ import annotations

from pathlib import Path
from threading import Barrier, Thread

import pytest

from sb.revoked_keys import (
    RevocationStoreError,
    effective_revoked_key_ids,
    initialized_revocation_path,
    load_revoked_key_ids,
    record_revoked_key_ids,
    revoked_key_path,
)


def test_concurrent_records_keep_both_keys(tmp_path: Path) -> None:
    start = Barrier(2)
    written: list[str] = []

    def write(key_id: str) -> None:
        start.wait()
        record_revoked_key_ids(tmp_path, [key_id])
        written.append(key_id)

    threads = [
        Thread(target=write, args=("key:one",)),
        Thread(target=write, args=("key:two",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(written) == ["key:one", "key:two"]
    assert load_revoked_key_ids(tmp_path) == frozenset({"key:one", "key:two"})


def test_missing_store_after_init_is_unsafe(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:gone"])
    revoked_key_path(tmp_path).unlink()
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        load_revoked_key_ids(tmp_path)


def test_symlink_revocation_file_is_unsafe(tmp_path: Path) -> None:
    target = tmp_path / "other"
    target.write_text("key:other\n", encoding="utf-8")
    revoked_key_path(tmp_path).symlink_to(target)
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        load_revoked_key_ids(tmp_path)
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        record_revoked_key_ids(tmp_path, ["key:next"])


def test_dangling_initialized_marker_symlink_is_unsafe(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"revoked-marker-{tmp_path.name}"
    initialized_revocation_path(tmp_path).symlink_to(outside)
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        record_revoked_key_ids(tmp_path, ["key:mark"])
    assert not outside.exists()


def test_truncated_initialized_store_is_unsafe(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:test"])
    revoked_key_path(tmp_path).write_text("", encoding="utf-8")
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        load_revoked_key_ids(tmp_path)


def test_partial_truncation_does_not_reactivate_revoked_key(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:other", "key:test"])
    path = revoked_key_path(tmp_path)
    path.write_bytes(path.read_bytes()[:-3])
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        load_revoked_key_ids(tmp_path)
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        effective_revoked_key_ids(tmp_path, ["key:new"])
