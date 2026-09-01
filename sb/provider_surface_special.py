"""Git, pointer, process, and descriptor provider-surface observations."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import subprocess
from contextlib import closing
from pathlib import Path

from sb.effect_values import JsonInput, digest
from sb.provider_observation_models import ProviderSurfaceObservationV1
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_specs import ProviderSurfaceSpec
from sb.sqlite_values import INTEGER_ROWS


def scan_git_surface(
    layout: ProviderSurfaceLayout,
    spec: ProviderSurfaceSpec,
    needles: tuple[bytes, ...],
) -> ProviderSurfaceObservationV1:
    root = layout.generation_root
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    errors: list[str] = []
    if spec.scanner_kind == "git_objects":
        command = ["git", "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"]
    else:
        command = ["git", "fsck", "--unreachable", "--no-reflogs", "--no-progress"]
    listed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False, env=env)
    if listed.returncode != 0:
        errors.append("GIT_OBJECT_SCAN_FAILED")
        object_ids: tuple[str, ...] = ()
    elif spec.scanner_kind == "git_objects":
        object_ids = tuple(line for line in listed.stdout.splitlines() if line)
    else:
        object_ids = tuple(
            fields[2] for line in listed.stdout.splitlines()
            if len(fields := line.split()) >= 3 and fields[0] == "unreachable"
        )
    records: list[dict[str, JsonInput]] = []
    matches = 0
    for object_id in sorted(object_ids):
        item = subprocess.run(
            ["git", "cat-file", "-p", object_id], cwd=root,
            capture_output=True, check=False, env=env,
        )
        if item.returncode != 0:
            errors.append("GIT_OBJECT_SCAN_FAILED")
            continue
        count = sum(item.stdout.count(needle) for needle in needles)
        matches += count
        records.append({
            "object_digest": "sha256:" + hashlib.sha256(item.stdout).hexdigest(),
            "byte_count": len(item.stdout), "match_count": count,
        })
    physical = tuple(path for path in (root / ".git" / "objects").rglob("*") if path.is_file())
    manifest = digest("surface", {"surface_id": spec.definition.surface_id, "objects": records})
    scan = digest("surface", {"manifest_digest": manifest, "errors": sorted(errors)})
    return ProviderSurfaceObservationV1(
        catalog_key=spec.definition.catalog_key,
        owner=spec.definition.owner,
        surface_id=spec.definition.surface_id,
        applicable=True,
        readable=not errors,
        manifest_digest=manifest, file_count=len(physical), row_count=0,
        object_count=len(records), fd_count=0, match_count=matches,
        error_count=len(errors), omission_count=int(bool(errors)), scan_digest=scan,
        errors=sorted(errors),
    )


def scan_pointer_surface(
    layout: ProviderSurfaceLayout,
    spec: ProviderSurfaceSpec,
) -> ProviderSurfaceObservationV1:
    pointer = layout.share_root / "vault"
    errors: list[str] = []
    target_digest = "sha256:" + "0" * 64
    if not pointer.is_symlink():
        errors.append("ACTIVE_POINTER_MISSING")
    else:
        try:
            target = os.readlink(pointer)
            target_digest = "sha256:" + hashlib.sha256(target.encode()).hexdigest()
            if Path(target).is_absolute() or pointer.resolve() != layout.generation_root.resolve():
                errors.append("ACTIVE_POINTER_INVALID")
        except OSError:
            errors.append("ACTIVE_POINTER_UNREADABLE")
    manifest = digest("surface", {"surface_id": spec.definition.surface_id, "target": target_digest})
    return ProviderSurfaceObservationV1(
        catalog_key=spec.definition.catalog_key,
        owner=spec.definition.owner,
        surface_id=spec.definition.surface_id,
        applicable=True,
        readable=not errors,
        manifest_digest=manifest, file_count=int(not errors), row_count=0, object_count=1,
        fd_count=0, match_count=0, error_count=len(errors), omission_count=int(bool(errors)),
        scan_digest=digest("surface", {"manifest_digest": manifest, "errors": errors}),
        errors=errors,
    )


def scan_process_memory_surface(
    layout: ProviderSurfaceLayout,
    spec: ProviderSurfaceSpec,
) -> ProviderSurfaceObservationV1:
    rows = 0
    processes = 0
    errors: list[str] = []
    try:
        journal = layout.request_root / "journal.db"
        with closing(sqlite3.connect(f"file:{journal}?mode=ro", uri=True)) as db:
            values = INTEGER_ROWS.validate_python(
                db.execute("SELECT process_id FROM reader_leases").fetchall()
            )
        rows = len(values)
        processes = len({process_id for (process_id,) in values})
        if rows:
            errors.append("PROVIDER_PROCESS_NOT_DRAINED")
    except sqlite3.Error:
        errors.append("PROCESS_REGISTRY_UNREADABLE")
    manifest = digest("surface", {"reader_leases": rows, "processes": processes})
    return ProviderSurfaceObservationV1(
        catalog_key=spec.definition.catalog_key,
        owner=spec.definition.owner,
        surface_id=spec.definition.surface_id,
        applicable=rows > 0,
        readable=not errors,
        manifest_digest=manifest, file_count=0, row_count=rows, object_count=processes,
        fd_count=0, match_count=0, error_count=len(errors), omission_count=int(bool(errors)),
        scan_digest=digest("surface", {"manifest_digest": manifest, "errors": errors}),
        errors=errors,
    )


def scan_fd_surface(
    layout: ProviderSurfaceLayout,
    spec: ProviderSurfaceSpec,
    needles: tuple[bytes, ...],
) -> ProviderSurfaceObservationV1:
    roots = tuple(
        path.resolve() for path in (
            layout.generation_root, layout.request_root, layout.state_root,
            layout.export_root, layout.backup_root, layout.staging_root, layout.retired_root,
        ) if path.exists()
    )
    records: list[dict[str, JsonInput]] = []
    matches = 0
    fd_count = 0
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
                managed = target.is_absolute() and any(
                    target.resolve().is_relative_to(root) for root in roots
                )
                if not managed:
                    continue
                metadata = descriptor.stat()
                fd_count += 1
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                raw = descriptor.read_bytes()
            except OSError:
                continue
            count = sum(raw.count(needle) for needle in needles)
            matches += count
            records.append({
                "locator_digest": hashlib.sha256(str(target).encode()).hexdigest(),
                "file_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "match_count": count,
            })
    manifest = digest("surface", {"fds": records, "fd_count": fd_count})
    return ProviderSurfaceObservationV1(
        catalog_key=spec.definition.catalog_key,
        owner=spec.definition.owner,
        surface_id=spec.definition.surface_id,
        applicable=fd_count > 0,
        readable=True,
        manifest_digest=manifest, file_count=len(records), row_count=0,
        object_count=0, fd_count=fd_count, match_count=matches,
        error_count=0, omission_count=0,
        scan_digest=digest("surface", {"manifest_digest": manifest, "errors": []}),
        errors=[],
    )
