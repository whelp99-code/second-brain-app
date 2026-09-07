"""Descriptor-safe staging inputs for provider generation mutations."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
from pathlib import Path

from sb.erasure import IngressIdentity, ReingressGate
from sb.generation_runtime_models import GenerationMutationError


def copy_legacy_content(source: Path, destination: Path) -> None:
    source_device = source.stat().st_dev
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(source)
        if relative.parts[0] in {".git", ".sb", "inbox"} or relative.name == "generation.json":
            continue
        metadata = path.stat(follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_dev != source_device
        ):
            raise GenerationMutationError("GENERATION_SOURCE_UNSAFE")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ = target.write_bytes(path.read_bytes())
        target.chmod(0o600)


def copy_pending_inbox(source: Path, destination: Path, state_root: Path) -> None:
    inbox = source / "inbox"
    if not inbox.is_dir() or inbox.is_symlink():
        return
    pending = tuple(
        path
        for path in sorted(inbox.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
        and not path.is_symlink()
        and not {".done", ".requests"}.intersection(path.relative_to(inbox).parts)
    )
    gate = ReingressGate(state_root / "reingress.db")
    try:
        payloads = tuple((path, path.read_bytes()) for path in pending)
        for path, payload in payloads:
            relative = path.relative_to(inbox).as_posix()
            gate.check(IngressIdentity(
                source=hashlib.sha256(f"inbox\0{relative}".encode()).hexdigest(),
                content=hashlib.sha256(payload).hexdigest(),
            ))
            gate.check_content(payload)
    finally:
        gate.close()
    for path, payload in payloads:
        target = destination / "inbox" / path.relative_to(inbox)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ = target.write_bytes(payload)
        target.chmod(0o600)


def copy_operational_ledger(source: Path, destination: Path) -> None:
    source_path = source / ".sb" / "ledger.db"
    if not source_path.is_file():
        return
    destination_path = destination / ".sb" / "ledger.db"
    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_db = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination_path)
    try:
        source_db.backup(destination_db)
        destination_db.commit()
    finally:
        destination_db.close()
        source_db.close()
    destination_path.chmod(0o600)
    source_log = source / ".sb" / "runs.log"
    if source_log.is_file() and not source_log.is_symlink():
        destination_log = destination / ".sb" / "runs.log"
        _ = destination_log.write_bytes(source_log.read_bytes())
        destination_log.chmod(0o600)


def remove_provisional_git(root: Path) -> None:
    git = root / ".git"
    if git.is_dir() and not git.is_symlink():
        shutil.rmtree(git)
    elif git.exists() or git.is_symlink():
        raise GenerationMutationError("GENERATION_HISTORY_INVALID")


def directory_fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
