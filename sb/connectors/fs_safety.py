"""Bounded, no-follow filesystem access beneath explicitly approved roots."""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, override

DIRECTORY_OPEN_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_CHUNK: Final = 65_536
_DENIED_SUFFIXES: Final = frozenset(
    {".cer", ".crt", ".der", ".key", ".keychain", ".keychain-db", ".p12", ".p7b", ".p7c", ".pem", ".pfx"}
)
_DENIED_NAMES: Final = frozenset({".netrc", "cookies", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa", "known_hosts"})
_SENSITIVE_WORD: Final = re.compile(
    r"(?:^|[._\-/])(?:access[-_]?token|auth[-_]?token|cookie|credential|"
    + r"private[-_]?key|refresh[-_]?token|secret|session|token)s?(?:[._\-/]|$)"
)
_REASONING_NAME: Final = re.compile(
    r"(?:^|[._\-/])(?:chain[-_]?of[-_]?thought|cot|hidden[-_]?reasoning)(?:[._\-/]|$)"
)


@dataclass(frozen=True, slots=True)
class SafeSourceFilesystemError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class SourceFilesystemLimits:
    max_entries: int = 10_000
    max_files: int = 5_000
    max_depth: int = 32
    max_file_bytes: int = 67_108_864
    max_total_bytes: int = 268_435_456

    def __post_init__(self) -> None:
        if min(self.max_entries, self.max_files, self.max_file_bytes, self.max_total_bytes) < 1 or self.max_depth < 0:
            raise SafeSourceFilesystemError("source filesystem limits must be positive")


@dataclass(frozen=True, slots=True)
class SourceFileMetadata:
    relative_path: str
    metadata: os.stat_result


@dataclass(frozen=True, slots=True)
class SkippedSourcePath:
    relative_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class SourceScan:
    files: tuple[SourceFileMetadata, ...]
    skipped: tuple[SkippedSourcePath, ...]


def is_denied_source_path(relative_path: str) -> bool:
    """Return whether a relative path belongs to a closed sensitive class."""
    lowered = relative_path.casefold()
    parts = tuple(part for part in lowered.split("/") if part)
    return (
        any(part == ".ssh" or "keychain" in part for part in parts)
        or any(part in _DENIED_NAMES for part in parts)
        or any(part == ".env" or part.startswith(".env.") for part in parts)
        or any(Path(part).suffix in _DENIED_SUFFIXES for part in parts)
        or _SENSITIVE_WORD.search(lowered) is not None
        or _REASONING_NAME.search(lowered) is not None
    )


def _assert_same(before: os.stat_result, after: os.stat_result, relative_path: str) -> None:
    same = (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_mode == after.st_mode
        and before.st_nlink == after.st_nlink
        and before.st_uid == after.st_uid
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )
    if not same:
        raise SafeSourceFilesystemError(f"source mutation observed: {relative_path}")


def _assert_owner_mode(metadata: os.stat_result, relative_path: str) -> None:
    if metadata.st_uid != os.getuid():
        raise SafeSourceFilesystemError(f"source owner refused: {relative_path}")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SafeSourceFilesystemError(f"source mode refused: {relative_path}")


def _translate_os_error(exc: OSError, relative_path: str) -> SafeSourceFilesystemError:
    if exc.errno in {errno.ELOOP, errno.EMLINK}:
        return SafeSourceFilesystemError(f"symlink source path refused: {relative_path}")
    return SafeSourceFilesystemError(f"source mutation observed: {relative_path}")


def _read_pinned(fd: int, relative_path: str, metadata: os.stat_result, max_bytes: int) -> bytes:
    before = os.fstat(fd)
    _assert_same(metadata, before, relative_path)
    if before.st_size > max_bytes:
        raise SafeSourceFilesystemError("source file bytes exceeds the resource budget")
    chunks = bytearray()
    while True:
        block = os.read(fd, min(_CHUNK, max_bytes - len(chunks) + 1))
        if not block:
            break
        chunks.extend(block)
        if len(chunks) > before.st_size or len(chunks) > max_bytes:
            raise SafeSourceFilesystemError("source file bytes exceeds the resource budget")
    if len(chunks) != before.st_size or os.read(fd, 1):
        raise SafeSourceFilesystemError(f"source mutation observed during read: {relative_path}")
    _assert_same(before, os.fstat(fd), relative_path)
    return bytes(chunks)


class SafeSourceFilesystem:
    """Read-only descriptor client constrained to an explicit root allowlist."""

    def __init__(self, approved_roots: Iterable[Path], limits: SourceFilesystemLimits | None = None) -> None:
        roots = tuple(approved_roots)
        if not roots:
            raise SafeSourceFilesystemError("at least one approved source root is required")
        self._approved: frozenset[str] = frozenset(os.path.abspath(root) for root in roots)
        self._limits: SourceFilesystemLimits = limits or SourceFilesystemLimits()

    def _open_root(self, root: Path) -> tuple[int, os.stat_result]:
        if root.is_symlink():
            raise SafeSourceFilesystemError("source root symlink refused")
        canonical = os.path.realpath(root)
        if canonical not in {os.path.realpath(path) for path in self._approved}:
            raise SafeSourceFilesystemError("source root is not approved")
        try:
            root_fd = os.open(canonical, DIRECTORY_OPEN_FLAGS)
        except OSError as exc:
            raise _translate_os_error(exc, ".") from exc
        metadata = os.fstat(root_fd)
        try:
            _assert_owner_mode(metadata, ".")
        except SafeSourceFilesystemError:
            os.close(root_fd)
            raise
        return root_fd, metadata

    def scan(self, root: Path, *, reject_denied: bool = False, reject_unsafe: bool = True) -> SourceScan:
        """No-follow metadata scan. `.git` is excluded at any depth."""
        root_fd, root_metadata = self._open_root(root)
        entries: list[SourceFileMetadata] = []
        skipped: list[SkippedSourcePath] = []
        entry_count = 0
        total_bytes = 0

        def refuse(relative: str, reason: str, *, reject: bool) -> None:
            if reject:
                label = "deny-class" if reason == "denied-path" else reason
                raise SafeSourceFilesystemError(f"{label} source path refused: {relative}")
            skipped.append(SkippedSourcePath(relative, reason))

        def walk(directory_fd: int, prefix: str, depth: int) -> None:
            nonlocal entry_count, total_bytes
            try:
                names = sorted(os.listdir(directory_fd))
            except OSError as exc:
                raise _translate_os_error(exc, prefix or ".") from exc
            for name in names:
                if name == ".git":
                    continue
                relative = f"{prefix}/{name}" if prefix else name
                entry_count += 1
                if entry_count > self._limits.max_entries:
                    raise SafeSourceFilesystemError("source entries exceed the resource budget")
                if is_denied_source_path(relative):
                    refuse(relative, "denied-path", reject=reject_denied)
                    continue
                try:
                    preview = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(preview.st_mode):
                        refuse(relative, "symlink", reject=reject_unsafe)
                        continue
                    _assert_owner_mode(preview, relative)
                    if stat.S_ISDIR(preview.st_mode):
                        if depth >= self._limits.max_depth:
                            raise SafeSourceFilesystemError("source depth exceeds the resource budget")
                        child_fd = os.open(name, DIRECTORY_OPEN_FLAGS, dir_fd=directory_fd)
                        try:
                            _assert_same(preview, os.fstat(child_fd), relative)
                            walk(child_fd, relative, depth + 1)
                        finally:
                            os.close(child_fd)
                        continue
                    if not stat.S_ISREG(preview.st_mode):
                        refuse(relative, "special", reject=reject_unsafe)
                        continue
                    if preview.st_nlink != 1:
                        refuse(relative, "hardlink", reject=reject_unsafe)
                        continue
                    if len(entries) >= self._limits.max_files:
                        raise SafeSourceFilesystemError("source file count exceeds the resource budget")
                    if preview.st_size > self._limits.max_file_bytes:
                        raise SafeSourceFilesystemError("source file bytes exceeds the resource budget")
                    total_bytes += preview.st_size
                    if total_bytes > self._limits.max_total_bytes:
                        raise SafeSourceFilesystemError("source aggregate bytes exceed the resource budget")
                    file_fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
                    try:
                        _assert_same(preview, os.fstat(file_fd), relative)
                    finally:
                        os.close(file_fd)
                    entries.append(SourceFileMetadata(relative, preview))
                except OSError as exc:
                    raise _translate_os_error(exc, relative) from exc

        try:
            walk(root_fd, "", 0)
            _assert_same(root_metadata, os.fstat(root_fd), ".")
            return SourceScan(tuple(sorted(entries, key=lambda item: item.relative_path)), tuple(skipped))
        finally:
            os.close(root_fd)

    def read_path(self, root: Path, relative_path: str) -> tuple[bytes, os.stat_result]:
        """Open one canonical regular file with no-follow checks and read it."""
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or pure.as_posix() != relative_path or any(part in {"", ".", ".."} for part in pure.parts):
            raise SafeSourceFilesystemError("source path escape detected")
        if is_denied_source_path(relative_path):
            raise SafeSourceFilesystemError(f"denied-path source path refused: {relative_path}")
        root_fd, _root_metadata = self._open_root(root)
        parent_fd = root_fd
        file_fd: int | None = None
        try:
            for part in pure.parts[:-1]:
                preview = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISLNK(preview.st_mode) or not stat.S_ISDIR(preview.st_mode):
                    kind = "symlink" if stat.S_ISLNK(preview.st_mode) else "special"
                    raise SafeSourceFilesystemError(f"{kind} source path refused: {relative_path}")
                _assert_owner_mode(preview, relative_path)
                child_fd = os.open(part, DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
                _assert_same(preview, os.fstat(child_fd), relative_path)
                if parent_fd != root_fd:
                    os.close(parent_fd)
                parent_fd = child_fd
            preview = os.stat(pure.name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(preview.st_mode) or not stat.S_ISREG(preview.st_mode):
                kind = "symlink" if stat.S_ISLNK(preview.st_mode) else "special"
                raise SafeSourceFilesystemError(f"{kind} source file refused: {relative_path}")
            _assert_owner_mode(preview, relative_path)
            if preview.st_nlink != 1:
                raise SafeSourceFilesystemError(f"hardlink source file refused: {relative_path}")
            if preview.st_size > self._limits.max_file_bytes:
                raise SafeSourceFilesystemError("source file bytes exceeds the resource budget")
            file_fd = os.open(pure.name, _FILE_FLAGS, dir_fd=parent_fd)
            _assert_same(preview, os.fstat(file_fd), relative_path)
            return _read_pinned(file_fd, relative_path, preview, self._limits.max_file_bytes), preview
        except OSError as exc:
            raise _translate_os_error(exc, relative_path) from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if parent_fd != root_fd:
                os.close(parent_fd)
            os.close(root_fd)
