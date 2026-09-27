"""Inspect first, then durably remove matched files within provider-managed roots."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path

from sb.managed_file_inspection import ManagedInspectionError, fingerprint, inspect_managed_file
from sb.managed_git import DISPOSING_PREFIX, git_directories, inspect_git_directory


def purge_matching_managed_copies(roots: Iterable[Path], needles: Sequence[bytes]) -> int:
    if not needles:
        return 0
    planned: dict[Path, tuple[int, ...]] = {}
    repositories: dict[Path, tuple[tuple[Path, tuple[int, ...]], ...]] = {}
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            raise ManagedInspectionError("MANAGED_ROOT_UNSAFE")
        git_roots = git_directories(root)
        for git_root in git_roots:
            if git_root.name.startswith(DISPOSING_PREFIX):
                repositories[git_root] = ()
            else:
                inspected_git = inspect_git_directory(git_root, needles)
                if inspected_git.matches:
                    repositories[git_root] = inspected_git.files
        for count, path in enumerate(sorted(root.rglob("*")), 1):
            if count > 100_000:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            if any(path == git_root or path.is_relative_to(git_root) for git_root in git_roots):
                continue
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
    # Rename durably before recursive disposal so interruption never becomes a clean scan.
    for repository, files in repositories.items():
        for path, expected in files:
            if fingerprint(path.lstat()) != expected:
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
        retired = repository if repository.name.startswith(DISPOSING_PREFIX) else repository.with_name(
            DISPOSING_PREFIX + hashlib.sha256(repository.name.encode()).hexdigest())
        directory = os.open(repository.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if retired != repository:
                os.rename(repository, retired)
                os.fsync(directory)
            shutil.rmtree(retired)
            os.fsync(directory)
        finally:
            os.close(directory)
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
    return len(planned) + len(repositories)
