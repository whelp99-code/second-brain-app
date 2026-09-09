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
        payloads = tuple((path, _read_pending_file(inbox, path.relative_to(inbox))) for path in pending)
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


def _read_pending_file(inbox: Path, relative: Path) -> bytes:
    descriptors: list[int] = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root = os.open(inbox, directory_flags)
        descriptors.append(root)
        device = os.fstat(root).st_dev
        parent = root
        for part in relative.parts[:-1]:
            parent = os.open(part, directory_flags, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_dev != device):
            raise GenerationMutationError("GENERATION_SOURCE_UNSAFE")
        chunks = bytearray()
        while len(chunks) <= before.st_size:
            block = os.read(fd, min(1024 * 1024, before.st_size - len(chunks) + 1))
            if not block:
                break
            chunks.extend(block)
        after = os.fstat(fd)
        if (len(chunks) != before.st_size or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns or after.st_ctime_ns != before.st_ctime_ns
                or after.st_nlink != 1):
            raise GenerationMutationError("GENERATION_SOURCE_UNSAFE")
        return bytes(chunks)
    except OSError as exc:
        raise GenerationMutationError("GENERATION_SOURCE_UNSAFE") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


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
    _copy_compiled_markers(source, destination)


def _copy_compiled_markers(source: Path, destination: Path) -> None:
    folder = source / ".sb" / "compiled"
    if not folder.exists() and not folder.is_symlink():
        return
    try:
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise GenerationMutationError("GENERATION_SOURCE_UNSAFE") from exc
    try:
        for name in sorted(os.listdir(descriptor)):
            if not name.endswith(".sha"):
                continue
            try:
                source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                    dir_fd=descriptor)
            except OSError as exc:
                raise GenerationMutationError("GENERATION_SOURCE_UNSAFE") from exc
            try:
                metadata = os.fstat(source_fd)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                        or metadata.st_uid != os.getuid() or metadata.st_dev != source.stat().st_dev):
                    raise GenerationMutationError("GENERATION_SOURCE_UNSAFE")
                marker = os.read(source_fd, 66)
                digest = marker.removesuffix(b"\n")
                if len(digest) != 64 or any(value not in b"0123456789abcdef" for value in digest):
                    raise GenerationMutationError("GENERATION_SOURCE_UNSAFE")
            finally:
                os.close(source_fd)
            target = destination / ".sb" / "compiled" / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _ = target.write_bytes(marker)
            target.chmod(0o600)
    finally:
        os.close(descriptor)


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
