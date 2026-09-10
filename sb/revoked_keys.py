"""Durable Jarvis signing-key revocations outside config.toml."""
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def revoked_key_path(state_root: Path) -> Path:
    return state_root / "revoked-jarvis-signing-key-ids"


def load_revoked_key_ids(state_root: Path) -> frozenset[str]:
    path = revoked_key_path(state_root)
    if path.is_symlink() or not path.is_file():
        return frozenset()
    return frozenset(line for line in path.read_text(encoding="utf-8").splitlines() if line)


def record_revoked_key_ids(state_root: Path, key_ids: Iterable[str]) -> None:
    incoming = {item for item in key_ids if item}
    if not incoming:
        return
    state_root.mkdir(parents=True, exist_ok=True)
    merged = sorted(load_revoked_key_ids(state_root) | incoming)
    path = revoked_key_path(state_root)
    pending = path.with_name(path.name + ".tmp")
    if pending.is_file() and not pending.is_symlink():
        pending.unlink()
    payload = ("\n".join(merged) + "\n").encode()
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        written = os.write(fd, payload)
        if written != len(payload):
            raise OSError("revocation record truncated")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(pending, path)
    directory = os.open(state_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def effective_revoked_key_ids(state_root: Path, configured: Iterable[str]) -> frozenset[str]:
    configured_ids = frozenset(item for item in configured if item)
    if configured_ids:
        record_revoked_key_ids(state_root, configured_ids)
    return load_revoked_key_ids(state_root) | configured_ids
