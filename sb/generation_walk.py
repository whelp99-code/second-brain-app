"""Enumerate content surfaces without entering excluded private trees."""
from __future__ import annotations

import os
from pathlib import Path


def surface_files(root: Path, *, include_derived: bool = False) -> tuple[tuple[Path, Path], ...]:
    """Return absolute/relative pairs in the existing full-path lexical order.

    Symlinks and other non-directory entries are returned for the caller's safety
    validation; none are followed. Only top-level .git/.sb trees are pruned.
    """
    pending = [(root, Path())]
    found: list[tuple[Path, Path]] = []
    while pending:
        folder, relative_folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                if not relative_folder.parts and (entry.name == ".git" or (
                    entry.name == ".sb" and not include_derived
                )):
                    continue
                path, relative = folder / entry.name, relative_folder / entry.name
                if entry.is_dir(follow_symlinks=False):
                    pending.append((path, relative))
                elif entry.name != "generation.json":
                    found.append((path, relative))
    return tuple(sorted(found, key=lambda item: item[1].as_posix()))
