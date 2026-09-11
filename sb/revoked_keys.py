"""Durable Jarvis signing-key revocations outside config.toml."""
from __future__ import annotations

import fcntl
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


def load_revoked_key_ids(state_root: Path) -> frozenset[str]:
    path = revoked_key_path(state_root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    if initialized_revocation_path(state_root).is_file() and not path.is_file():
        raise RevocationStoreError("REVOCATION_STORE_UNSAFE")
    if not path.is_file():
        return frozenset()
    return frozenset(line for line in path.read_text(encoding="utf-8").splitlines() if line)


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
        merged = sorted(load_revoked_key_ids(state_root) | incoming)
        payload = ("\n".join(merged) + "\n").encode()
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
        marker = initialized_revocation_path(state_root)
        if not marker.exists():
            marker.write_text("1\n", encoding="utf-8")
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
