"""Durable Jarvis signing-key revocations outside config.toml."""
from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


class RevocationStoreError(Exception):
    """Raised when the revocation file cannot be used safely."""


def revoked_key_path(state_root: Path) -> Path:
    return state_root / "revoked-jarvis-signing-key-ids"


def initialized_revocation_path(state_root: Path) -> Path:
    return state_root / "revoked-jarvis-signing-key-ids.initialized"


def revocation_journal_path(state_root: Path) -> Path:
    return state_root / "revoked-jarvis-signing-key-ids.journal"


def _reject_unsafe(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")


def _digest_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_marker(marker: Path, digest_hex: str) -> None:
    _reject_unsafe(marker)
    marker_tmp = marker.with_name(marker.name + ".tmp")
    if marker_tmp.exists() or marker_tmp.is_symlink():
        marker_tmp.unlink(missing_ok=True)
        if marker_tmp.is_symlink() or marker_tmp.exists():
            raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    marker_fd = os.open(marker_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(marker_fd, (digest_hex + "\n").encode("ascii"))
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)
    os.replace(marker_tmp, marker)


def _recover_journal(state_root: Path) -> None:
    journal = revocation_journal_path(state_root)
    path = revoked_key_path(state_root)
    marker = initialized_revocation_path(state_root)
    _reject_unsafe(journal)
    if not journal.is_file():
        return
    raw = journal.read_bytes()
    split = raw.find(b"\n")
    if split < 0:
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    jdigest = raw[:split].decode("ascii").strip()
    jpayload = raw[split + 1 :]
    if _digest_hex(jpayload) != jdigest:
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    if path.is_file() and _digest_hex(path.read_bytes()) == jdigest:
        _write_marker(marker, jdigest)
        journal.unlink()


def load_revoked_key_ids(state_root: Path) -> frozenset[str]:
    path = revoked_key_path(state_root)
    marker = initialized_revocation_path(state_root)
    _reject_unsafe(path)
    _reject_unsafe(marker)
    _recover_journal(state_root)
    if marker.is_file() and not path.is_file():
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    if not path.is_file():
        return frozenset()
    payload = path.read_bytes()
    if marker.is_file():
        token = marker.read_text(encoding="utf-8").strip()
        if token == "1" or token != _digest_hex(payload):
            raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    text = payload.decode("utf-8")
    keys = frozenset(line for line in text.splitlines() if line)
    if marker.is_file() and not keys:
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    return keys


def record_revoked_key_ids(state_root: Path, key_ids: Iterable[str]) -> None:
    incoming = {item for item in key_ids if item}
    if not incoming:
        return
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = revoked_key_path(state_root).with_name("revoked-jarvis-signing-key-ids.lock")
    if lock_path.is_symlink():
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    tmp_name = ""
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _recover_journal(state_root)
        merged = sorted(load_revoked_key_ids(state_root) | incoming)
        payload = ("\n".join(merged) + "\n").encode()
        digest = _digest_hex(payload)
        journal = revocation_journal_path(state_root)
        _reject_unsafe(journal)
        journal_fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.write(journal_fd, (digest + "\n").encode("ascii") + payload)
            os.fsync(journal_fd)
        finally:
            os.close(journal_fd)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".revoked-", suffix=".tmp", dir=str(state_root))
        try:
            written = os.write(tmp_fd, payload)
            if written != len(payload):
                raise OSError("revocation record truncated")
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        os.replace(tmp_name, revoked_key_path(state_root))
        tmp_name = ""
        _write_marker(initialized_revocation_path(state_root), digest)
        journal.unlink()
        directory = os.open(state_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def effective_revoked_key_ids(state_root: Path, configured: Iterable[str]) -> frozenset[str]:
    configured_ids = frozenset(item for item in configured if item)
    if configured_ids:
        record_revoked_key_ids(state_root, configured_ids)
    return load_revoked_key_ids(state_root) | configured_ids
