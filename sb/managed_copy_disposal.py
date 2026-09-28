"""Pre-activation copy disposal evidence; no source text is retained in the journal."""

from __future__ import annotations

import hashlib
import sqlite3
import stat
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from sb.effect_values import JsonValue, digest, format_instant
from sb.managed_backup_manifest import validate_managed_backups
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.managed_git import git_directories, inspect_git_directory


class _ExportSurface(Protocol):
    @property
    def root(self) -> Path: ...

    def invalidate(self, identities: set[str], now: datetime) -> tuple[str, ...]: ...


def initialize_copy_disposals(db: sqlite3.Connection) -> None:
    _ = db.execute("""CREATE TABLE IF NOT EXISTS managed_copy_disposals (
        operation_id TEXT PRIMARY KEY, binding_digest TEXT NOT NULL,
        inventory_digest TEXT NOT NULL, observed_at TEXT NOT NULL
    )""")


def copy_disposal_binding(operation_digest: str, generation_id: str, roots: Sequence[Path]) -> str:
    return digest("surface", {"operation": operation_digest, "generation": generation_id,
        "roots": [hashlib.sha256(str(root.absolute()).encode()).hexdigest() for root in roots]})


def copy_inventory(roots: Sequence[Path], needles: Sequence[bytes] = ()) -> str:
    """Stable content inventory independent of open descriptor counts and observation time."""
    records: list[JsonValue] = []
    for index, root in enumerate(roots):
        if not root.is_dir() or root.is_symlink():
            raise ManagedInspectionError("MANAGED_ROOT_UNSAFE")
        git_roots = git_directories(root)
        for git_root in git_roots:
            inspected_git = inspect_git_directory(git_root, needles)
            if inspected_git.matches:
                raise ManagedInspectionError("MANAGED_COPY_REMAINS")
            records.append({"root": index,
                "path": hashlib.sha256(git_root.relative_to(root).as_posix().encode()).hexdigest(),
                "digest": inspected_git.digest, "objects": inspected_git.objects})
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
                raise ManagedInspectionError("MANAGED_COPY_REMAINS")
            records.append({"root": index,
                "path": hashlib.sha256(path.relative_to(root).as_posix().encode()).hexdigest(),
                "digest": inspected.digest, "bytes": inspected.byte_count})
    return digest("surface", {"files": records})


def require_copy_disposal(
    db: sqlite3.Connection, operation_id: str, binding: str, roots: Sequence[Path] | None,
) -> None:
    row = cast(sqlite3.Row | None, db.execute(
        "SELECT binding_digest,inventory_digest FROM managed_copy_disposals WHERE operation_id=?", (operation_id,),
    ).fetchone())
    if row is None or row[0] != binding:
        raise ManagedInspectionError("MANAGED_DISPOSAL_EVIDENCE_MISSING")
    if roots is not None and row[1] != copy_inventory(roots):
        raise ManagedInspectionError("MANAGED_DISPOSAL_INVENTORY_CHANGED")


def prepare_copy_disposal(
    db: sqlite3.Connection, operation_id: str, binding: str, *, backup_root: Path,
    exports: _ExportSurface, identities: set[str], needles: tuple[bytes, ...] | None,
    now: datetime, authority: Callable[[], None], barrier: Callable[[str], None],
) -> None:
    """Caller holds the generation writer. None means the original generation is gone."""
    roots = (backup_root, exports.root)
    if needles is None:
        require_copy_disposal(db, operation_id, binding, roots)
        authority()
        return
    if not needles or any(not needle for needle in needles):
        raise ManagedInspectionError("MANAGED_DISPOSAL_TARGET_MISSING")
    _ = purge_matching_managed_copies((backup_root,), needles)
    barrier("backup_disposal")
    _ = exports.invalidate(identities, now)
    barrier("export_disposal")
    validate_managed_backups(backup_root)
    inventory = copy_inventory(roots, needles)
    authority()
    _ = db.execute("""INSERT INTO managed_copy_disposals VALUES(?,?,?,?)
        ON CONFLICT(operation_id) DO UPDATE SET binding_digest=excluded.binding_digest,
        inventory_digest=excluded.inventory_digest,observed_at=excluded.observed_at""",
        (operation_id, binding, inventory, format_instant(now)))
    barrier("disposal_parent_fsync")
