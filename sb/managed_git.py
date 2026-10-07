"""Bounded decoded inspection of nested, bare, and renamed managed Git copies."""

from __future__ import annotations

import hashlib
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sb.managed_inspection_stream import ManagedInspectionError, fingerprint

_MAX_BYTES: Final = 64 * 1024 * 1024
_MAX_OBJECTS: Final = 100_000
_MAX_PACKS: Final = 128
_HEADER: Final = re.compile(rb"[0-9a-f]{40}(?:[0-9a-f]{24})? (blob|tree|commit|tag) ([0-9]+)")
DISPOSING_PREFIX: Final = ".sb-disposing-git-"


@dataclass(frozen=True, slots=True)
class GitInspection:
    root: Path
    digest: str
    matches: int
    objects: int
    files: tuple[tuple[Path, tuple[int, ...]], ...]


def git_directories(root: Path) -> tuple[Path, ...]:
    """Validate the walk before Git can follow any filesystem indirection."""
    found: list[Path] = []
    pending = [root]
    count = 0
    while pending:
        folder = pending.pop()
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ManagedInspectionError("MANAGED_ROOT_UNSAFE")
        children = sorted(folder.iterdir())
        is_git = (folder / "objects").is_dir() or folder.name.startswith(DISPOSING_PREFIX)
        if is_git:
            found.append(folder)
        for path in children:
            count += 1
            if count > _MAX_OBJECTS:
                raise ManagedInspectionError("MANAGED_GIT_BUDGET")
            metadata = path.lstat()
            if metadata.st_uid != os.getuid() or stat.S_ISLNK(metadata.st_mode):
                raise ManagedInspectionError("MANAGED_SURFACE_UNSAFE")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ManagedInspectionError("MANAGED_SURFACE_UNSAFE")
            elif path.name == ".git":
                raise ManagedInspectionError("MANAGED_GIT_INDIRECTION")
    # An objects directory cannot itself contain a second independent repository.
    return tuple(path for path in found if not any(parent in found for parent in path.parents))


def _git_output(root: Path, arguments: Sequence[str]) -> bytes:
    """Bound every Git inspection command by output bytes and a hard deadline."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    with subprocess.Popen([sys.executable, "-m", "sb.managed_git_command", f"--git-dir={root}", *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as process:
        if process.stdout is None:
            raise ManagedInspectionError("MANAGED_GIT_SCAN_FAILED")
        deadline = time.monotonic() + 30
        output = bytearray()
        try:
            with selectors.DefaultSelector() as ready:
                _ = ready.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not ready.select(remaining):
                        raise ManagedInspectionError("MANAGED_GIT_TIMEOUT")
                    block = os.read(process.stdout.fileno(), 65_536)
                    if not block:
                        break
                    output.extend(block)
                    if len(output) > _MAX_BYTES:
                        raise ManagedInspectionError("MANAGED_GIT_BUDGET")
            if process.wait(timeout=max(deadline - time.monotonic(), 0.001)) != 0:
                raise ManagedInspectionError("MANAGED_GIT_SCAN_FAILED")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagedInspectionError("MANAGED_GIT_SCAN_FAILED") from exc
        finally:
            if process.poll() is None:
                process.kill()
                _ = process.wait()
        return bytes(output)


def _object_stream(root: Path) -> bytes:
    return _git_output(root, ("cat-file", "--batch-all-objects", "--batch"))


def _pack_inventory(root: Path) -> set[bytes]:
    """Git verifies both pack/index checksums before any batch inventory is trusted."""
    folder = root / "objects/pack"
    if not folder.exists():
        return set()
    paths = tuple(folder.iterdir())
    packs = {path.stem for path in paths if path.suffix == ".pack"}
    indexes = {path.stem for path in paths if path.suffix == ".idx"}
    if packs != indexes:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if len(packs) > _MAX_PACKS:
        raise ManagedInspectionError("MANAGED_GIT_BUDGET")
    objects: set[bytes] = set()
    for name in sorted(packs):
        output = _git_output(root, ("verify-pack", "-v", str(folder / (name + ".idx"))))
        inventory = {line.split(b" ", 1)[0] for line in output.splitlines()
                     if re.match(rb"^[0-9a-f]{40}(?:[0-9a-f]{24})? ", line)}
        with (folder / (name + ".pack")).open("rb") as source:
            header = source.read(12)
            hash_size = 32 if len(name) == 69 else 20
            _ = source.seek(-hash_size, os.SEEK_END)
            checksum = source.read(hash_size).hex()
        if (len(header) != 12 or header[:4] != b"PACK" or name != "pack-" + checksum
                or int.from_bytes(header[8:12], "big") != len(inventory)):
            raise ManagedInspectionError("MANAGED_GIT_STREAM_INVALID")
        objects.update(inventory)
        if len(objects) > _MAX_OBJECTS:
            raise ManagedInspectionError("MANAGED_GIT_BUDGET")
    return objects


def inspect_git_directory(
    root: Path, needles: Sequence[bytes], *, decoded: Callable[[bytes], int] | None = None,
) -> GitInspection:
    """Require a complete batch framing and stable private files, including unreachable objects."""
    if root.name.startswith(DISPOSING_PREFIX):
        raise ManagedInspectionError("MANAGED_GIT_DISPOSAL_INCOMPLETE")
    for relative in ("objects/info/alternates", "objects/info/http-alternates", "commondir", "shallow"):
        if (root / relative).exists():
            raise ManagedInspectionError("MANAGED_GIT_INDIRECTION")
    files: list[tuple[Path, tuple[int, ...]]] = []
    sha = hashlib.sha256()
    matches = 0
    total = 0
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ManagedInspectionError("MANAGED_SURFACE_UNSAFE")
        total += metadata.st_size
        if total > _MAX_BYTES:
            raise ManagedInspectionError("MANAGED_GIT_BUDGET")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            if fingerprint(os.fstat(source.fileno())) != fingerprint(metadata):
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
            raw = source.read(_MAX_BYTES + 1)
        if len(raw) != metadata.st_size:
            raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
        sha.update(path.relative_to(root).as_posix().encode() + b"\0" + raw)
        matches += sum(raw.count(needle) for needle in needles if needle)
        files.append((path, fingerprint(metadata)))
    packed = _pack_inventory(root)
    stream = _object_stream(root)
    if len(stream) > max(total, 1) * 1000:
        raise ManagedInspectionError("MANAGED_GIT_BUDGET")
    offset = 0
    objects = 0
    seen: set[bytes] = set()
    while offset < len(stream):
        end = stream.find(b"\n", offset, offset + 128)
        header = _HEADER.fullmatch(stream[offset:end]) if end >= 0 else None
        if header is None:
            raise ManagedInspectionError("MANAGED_GIT_STREAM_INVALID")
        length = int(header.group(2))
        start = end + 1
        offset = start + length
        if offset >= len(stream) or stream[offset:offset + 1] != b"\n":
            raise ManagedInspectionError("MANAGED_GIT_STREAM_INVALID")
        payload = stream[start:offset]
        offset += 1
        objects += 1
        if objects > _MAX_OBJECTS:
            raise ManagedInspectionError("MANAGED_GIT_BUDGET")
        oid = header.group(0).split(b" ", 1)[0]
        framed = header.group(1) + b" " + str(length).encode() + b"\0" + payload
        actual = hashlib.sha1(framed).hexdigest() if len(oid) == 40 else hashlib.sha256(framed).hexdigest()
        if oid in seen or actual.encode() != oid:
            raise ManagedInspectionError("MANAGED_GIT_STREAM_INVALID")
        seen.add(oid)
        matches += sum(payload.count(needle) for needle in needles if needle)
        if decoded is not None:
            matches += decoded(payload)
    if not packed.issubset(seen):
        raise ManagedInspectionError("MANAGED_GIT_STREAM_INVALID")
    sha.update(stream)
    if tuple(path for path in sorted(root.rglob("*")) if path.is_file()) != tuple(path for path, _ in files):
        raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
    for path, expected in files:
        if fingerprint(path.lstat()) != expected:
            raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
    return GitInspection(root, "sha256:" + sha.hexdigest(), matches, objects, tuple(files))
