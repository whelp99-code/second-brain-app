"""Inspect first, then durably remove matched files within provider-managed roots."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path

from sb.managed_file_inspection import ManagedInspectionError, fingerprint, inspect_managed_file


def purge_matching_managed_copies(roots: Iterable[Path], needles: Sequence[bytes]) -> int:
    if not needles:
        return 0
    planned: dict[Path, tuple[int, ...]] = {}
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            raise ManagedInspectionError("MANAGED_ROOT_UNSAFE")
        for count, path in enumerate(sorted(root.rglob("*")), 1):
            if count > 100_000:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            inspected = inspect_managed_file(path, needles)
            if inspected.matches:
                planned[path] = inspected.fingerprint
                for suffix in (".sha256", ".verified.json"):
                    companion = path.with_name(path.name + suffix)
                    if companion.exists() or companion.is_symlink():
                        planned[companion] = inspect_managed_file(companion, ()).fingerprint
    # Keep the content-bearing archive until its sidecars are gone. A crash can then
    # re-find the original match and finish disposal without a plaintext deletion plan.
    ordered = sorted(planned.items(), key=lambda item: (
        not item[0].name.endswith((".sha256", ".verified.json")), item[0]))
    for path, expected in ordered:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            actual = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if fingerprint(actual) != expected:
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
            os.unlink(path.name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)
    return len(planned)
