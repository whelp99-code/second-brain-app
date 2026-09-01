"""Regular-file and SQLite observation for fixed provider surfaces."""

from __future__ import annotations

import hashlib
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from sb.effect_values import JsonInput, digest
from sb.provider_observation_models import ProviderSurfaceObservationV1
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_specs import (
    ProviderRootName,
    ProviderSurfaceSpec,
    SurfaceSelection,
)
from sb.sqlite_values import OPTIONAL_INTEGER_ROW, OPTIONAL_TEXT_ROW, TEXT_ROWS


@dataclass(frozen=True, slots=True)
class _SelectedFiles:
    files: tuple[tuple[Path, str], ...]
    errors: tuple[str, ...]
    omissions: int


def _root(layout: ProviderSurfaceLayout, name: ProviderRootName) -> Path:
    roots = {
        "generation": layout.generation_root,
        "requests": layout.request_root,
        "state": layout.state_root,
        "share": layout.share_root,
        "exports": layout.export_root,
        "backups": layout.backup_root,
        "staging": layout.staging_root,
        "retired": layout.retired_root,
    }
    return roots[name]


def _include(relative: Path, selection: SurfaceSelection) -> bool:
    if selection.first_prefixes and not relative.parts[0].startswith(selection.first_prefixes):
        return False
    if selection.excluded_parts and set(relative.parts).intersection(selection.excluded_parts):
        return False
    return not selection.suffixes or relative.name.endswith(selection.suffixes)


def _select(layout: ProviderSurfaceLayout, spec: ProviderSurfaceSpec) -> _SelectedFiles:
    found: list[tuple[Path, str]] = []
    errors: list[str] = []
    omissions = 0
    for location_index, selection in enumerate(spec.selections):
        owner_root = _root(layout, selection.root)
        target = owner_root.joinpath(*selection.relative)
        if not owner_root.is_dir() or owner_root.is_symlink():
            errors.append("MANAGED_ROOT_UNREADABLE")
            omissions += 1
            continue
        if not target.exists() and not target.is_symlink():
            if selection.required:
                errors.append("MANAGED_SURFACE_MISSING")
                omissions += 1
            continue
        if target.is_symlink():
            errors.append("MANAGED_SURFACE_UNSAFE")
            omissions += 1
            continue
        candidates = (target,) if target.is_file() else tuple(target.rglob("*"))
        for path in sorted(candidates, key=lambda item: item.as_posix()):
            if path.is_dir():
                continue
            relative = path.relative_to(target) if target.is_dir() else Path(path.name)
            if not _include(relative, selection):
                continue
            locator = hashlib.sha256(
                f"{spec.definition.surface_id}\0{location_index}\0{relative.as_posix()}".encode()
            ).hexdigest()
            found.append((path, locator))
    return _SelectedFiles(tuple(found), tuple(errors), omissions)


def _sqlite_stats(path: Path, tables: tuple[str, ...]) -> tuple[int, int, set[str], tuple[str, ...]]:
    errors: list[str] = []
    rows = 0
    free_pages = 0
    seen: set[str] = set()
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            check = OPTIONAL_TEXT_ROW.validate_python(
                connection.execute("PRAGMA quick_check").fetchone()
            )
            if check != ("ok",):
                errors.append("SQLITE_INTEGRITY_FAILED")
            free = OPTIONAL_INTEGER_ROW.validate_python(
                connection.execute("PRAGMA freelist_count").fetchone()
            )
            free_pages = 0 if free is None else free[0]
            names = TEXT_ROWS.validate_python(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall())
            available = {name for (name,) in names if name.replace("_", "").isalnum()}
            selected = available if not tables else available.intersection(tables)
            seen.update(selected)
            for table in sorted(selected):
                count = OPTIONAL_INTEGER_ROW.validate_python(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                )
                if count is not None:
                    rows += count[0]
    except sqlite3.Error:
        errors.append("SQLITE_SCAN_FAILED")
    return rows, free_pages, seen, tuple(errors)


def scan_file_surface(
    layout: ProviderSurfaceLayout,
    spec: ProviderSurfaceSpec,
    needles: tuple[bytes, ...],
) -> ProviderSurfaceObservationV1:
    selected = _select(layout, spec)
    records: list[dict[str, JsonInput]] = []
    errors = list(selected.errors)
    rows = 0
    free_pages = 0
    seen_tables: set[str] = set()
    matches = 0
    file_count = 0
    for path, locator in selected.files:
        try:
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                errors.append("MANAGED_SURFACE_UNSAFE")
                continue
            raw = path.read_bytes()
        except OSError:
            errors.append("MANAGED_SURFACE_UNREADABLE")
            continue
        count = sum(raw.count(needle) for needle in needles)
        file_count += 1
        matches += count
        records.append({
            "locator_digest": locator,
            "file_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "match_count": count,
        })
        if spec.scanner_kind == "sqlite" and path.name.endswith(".db"):
            found_rows, found_free, found_tables, sqlite_errors = _sqlite_stats(path, spec.tables)
            rows += found_rows
            free_pages += found_free
            seen_tables.update(found_tables)
            errors.extend(sqlite_errors)
    missing_tables = set(spec.tables).difference(seen_tables)
    omissions = selected.omissions + len(missing_tables)
    errors.extend("SQLITE_TABLE_MISSING" for _table in sorted(missing_tables))
    manifest = digest("surface", {"surface_id": spec.definition.surface_id, "files": records})
    scan = digest("surface", {
        "manifest_digest": manifest,
        "row_count": rows,
        "free_pages": free_pages,
        "match_count": matches,
        "errors": sorted(errors),
        "omission_count": omissions,
    })
    return ProviderSurfaceObservationV1(
        catalog_key=spec.definition.catalog_key,
        owner=spec.definition.owner,
        surface_id=spec.definition.surface_id,
        applicable=True,
        readable=not errors,
        manifest_digest=manifest, file_count=file_count, row_count=rows,
        object_count=free_pages, fd_count=0, match_count=matches,
        error_count=len(errors), omission_count=omissions, scan_digest=scan,
        errors=sorted(errors),
    )
