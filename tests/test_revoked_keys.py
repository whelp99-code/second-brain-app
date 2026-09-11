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
    revocation_journal_path,
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


def test_legacy_marker_missing_complete_line_is_unsafe(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:other", "key:test"])
    initialized_revocation_path(tmp_path).write_text("1\n", encoding="utf-8")
    revoked_key_path(tmp_path).write_text("key:other\n", encoding="utf-8")
    with pytest.raises(RevocationStoreError, match="REVOCATION_STORE_UNSAFE"):
        load_revoked_key_ids(tmp_path)


def test_interrupted_marker_update_recovers_then_retry_records(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:a"])
    payload = b"key:a\nkey:b\n"
    digest = __import__("hashlib").sha256(payload).hexdigest()
    revocation_journal_path(tmp_path).write_bytes((digest + "\n").encode("ascii") + payload)
    revoked_key_path(tmp_path).write_bytes(payload)
    assert load_revoked_key_ids(tmp_path) == frozenset({"key:a", "key:b"})
    record_revoked_key_ids(tmp_path, ["key:c"])
    assert load_revoked_key_ids(tmp_path) == frozenset({"key:a", "key:b", "key:c"})


def test_concurrent_journal_recover_does_not_raise_file_not_found(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:a"])
    payload = b"key:a\nkey:b\n"
    digest = __import__("hashlib").sha256(payload).hexdigest()
    revocation_journal_path(tmp_path).write_bytes((digest + "\n").encode("ascii") + payload)
    revoked_key_path(tmp_path).write_bytes(payload)
    errors: list[str] = []
    start = Barrier(2)

    def reader() -> None:
        start.wait()
        try:
            load_revoked_key_ids(tmp_path)
        except (OSError, RevocationStoreError) as exc:
            errors.append(type(exc).__name__)

    threads = [Thread(target=reader), Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert load_revoked_key_ids(tmp_path) == frozenset({"key:a", "key:b"})


def test_reader_uses_the_writer_lock_file(tmp_path: Path) -> None:
    record_revoked_key_ids(tmp_path, ["key:a"])
    load_revoked_key_ids(tmp_path)
    assert (tmp_path / "revoked-jarvis-signing-key-ids.lock").is_file()
    assert not (tmp_path / ".revoked.lock").exists()


def test_missing_state_root_is_empty_not_crash(tmp_path: Path) -> None:
    missing = tmp_path / "no-state"
    assert load_revoked_key_ids(missing) == frozenset()
