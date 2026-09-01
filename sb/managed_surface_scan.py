"""Generic physical scan used by erasure and vector verification."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from sb.effect_values import JsonValue, digest
from sb.sqlite_values import OPTIONAL_INTEGER_ROW, OPTIONAL_TEXT_ROW, TEXT_ROWS


@dataclass(frozen=True, slots=True)
class SurfaceInventoryEntry:
    owner: str
    surface_id: str
    manifest_digest: str
    readable: bool
    file_count: int
    row_count: int
    object_count: int
    fd_count: int
    scan_digest: str
    matches: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfaceInventory:
    entries: tuple[SurfaceInventoryEntry, ...]
    manifest_digest: str
    scan_errors: int
    matches: int


def _process_fd_count(root: Path) -> int:
    resolved = root.resolve()
    count = 0
    for process in Path("/proc").glob("[0-9]*"):
        try:
            if process.stat().st_uid != os.getuid():
                continue
            descriptors = tuple((process / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = Path(os.readlink(descriptor).removesuffix(" (deleted)"))
                if target.is_absolute() and target.resolve().is_relative_to(resolved):
                    count += 1
            except OSError:
                continue
    return count


def _sqlite_rows(path: Path) -> tuple[int, tuple[str, ...]]:
    errors: list[str] = []
    rows = 0
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        check = OPTIONAL_TEXT_ROW.validate_python(
            connection.execute("PRAGMA quick_check").fetchone()
        )
        if check != ("ok",):
            errors.append("SQLITE_INTEGRITY_FAILED")
        tables = TEXT_ROWS.validate_python(connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall())
        for (table,) in tables:
            if not table.replace("_", "").isalnum():
                errors.append("SQLITE_TABLE_INVALID")
                continue
            value = OPTIONAL_INTEGER_ROW.validate_python(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            )
            if value is not None:
                rows += value[0]
        connection.close()
    except sqlite3.Error:
        errors.append("SQLITE_SCAN_FAILED")
    return rows, tuple(errors)


def _scan_regular(root: Path, needles: Sequence[bytes]) -> SurfaceInventoryEntry:
    file_count = 0
    matches = 0
    errors: list[str] = []
    rows: list[dict[str, JsonValue]] = []
    row_count = 0
    object_count = 0
    fd_count = 0
    try:
        if not root.is_dir() or root.is_symlink():
            raise OSError("managed root missing or unsafe")
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                errors.append("NON_REGULAR_SURFACE")
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                errors.append("UNREADABLE_SURFACE")
                continue
            count = sum(raw.count(needle) for needle in needles)
            matches += count
            file_count += 1
            if path.suffix == ".db":
                found_rows, sqlite_errors = _sqlite_rows(path)
                row_count += found_rows
                errors.extend(sqlite_errors)
            rows.append({
                "surface_id": hashlib.sha256(
                    path.relative_to(root).as_posix().encode("utf-8")
                ).hexdigest(),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "matches": count,
            })
        if (root / ".git").is_dir():
            listed = subprocess.run(
                ["git", "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"],
                cwd=root, check=False, capture_output=True, text=True,
            )
            if listed.returncode != 0:
                errors.append("GIT_OBJECT_SCAN_FAILED")
            else:
                for oid in listed.stdout.splitlines():
                    item = subprocess.run(
                        ["git", "cat-file", "-p", oid], cwd=root,
                        check=False, capture_output=True,
                    )
                    if item.returncode != 0:
                        errors.append("GIT_OBJECT_SCAN_FAILED")
                        continue
                    object_count += 1
                    matches += sum(item.stdout.count(needle) for needle in needles)
        fd_count = _process_fd_count(root)
    except OSError:
        errors.append("SURFACE_ENUMERATION_FAILED")
    scan_digest = digest(
        "surface",
        {"files": rows, "objects": object_count, "fds": fd_count, "errors": sorted(errors)},
    )
    root_digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    return SurfaceInventoryEntry(
        owner="second_brain", surface_id=root_digest,
        manifest_digest=digest("surface", {"root": root_digest}), readable=not errors,
        file_count=file_count, row_count=row_count, object_count=object_count,
        fd_count=fd_count, scan_digest=scan_digest, matches=matches,
        errors=tuple(sorted(errors)),
    )


def scan_managed_surfaces(
    roots: Iterable[Path],
    needles: Sequence[bytes],
) -> SurfaceInventory:
    entries = tuple(_scan_regular(root, needles) for root in roots)
    payload = {"entries": [asdict(entry) for entry in entries]}
    return SurfaceInventory(
        entries=entries,
        manifest_digest=digest("surface", payload),
        scan_errors=sum(len(entry.errors) for entry in entries),
        matches=sum(entry.matches for entry in entries),
    )
