"""Operator-local company snapshots; no runtime authority or in-place restore."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, ValidationError

from sb.company_memory import CandidateRow, CompanyMemoryError
from sb.company_memory_authority import canonical_workspace_id
from sb.company_memory_sources import (
    CompanySourceBinding,
    CompanySourceProfile,
    resolve_company_source,
)
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_models import ClosedModel

_CANDIDATE_COLUMNS = (
    "workspace_id",
    "candidate_id",
    "source_system",
    "source_locator",
    "source_event_id",
    "content",
    "content_digest",
    "parser_version",
    "locator_json",
    "owner",
    "projects_json",
    "policy_revision",
    "deletion_sequence",
    "deletion_set_root",
    "state",
    "accepted_at",
    "rejected_at",
    "processed_at",
)
_RECEIPT_COLUMNS = (
    "workspace_id",
    "request_digest",
    "receipt_id",
    "receipt_digest",
    "operation",
    "candidate_id",
    "result_json",
    "created_at",
)
type SnapshotReceiptRow = tuple[str, str, str, str, str, str, str, str]


class CompanySnapshotResult(ClosedModel):
    status: Literal["created", "verified"]
    workspace_id: str
    manifest_sha256: str
    database_sha256: str
    candidate_count: int
    receipt_count: int
    source_count: int


class CompanySnapshotManifest(ClosedModel):
    schema_version: Literal[1]
    workspace_id: str
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: list[JsonObject]
    receipts: list[JsonObject]
    sources: dict[str, CompanySourceBinding]

    def result(
        self, status: Literal["created", "verified"], manifest_sha256: str
    ) -> CompanySnapshotResult:
        return CompanySnapshotResult(
            status=status,
            workspace_id=self.workspace_id,
            manifest_sha256=manifest_sha256,
            database_sha256=self.database_sha256,
            candidate_count=len(self.candidates),
            receipt_count=len(self.receipts),
            source_count=len(self.sources),
        )


def _file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _inventory(
    database: Path,
    workspace_id: str,
    profile: CompanySourceProfile,
    personal_roots: tuple[Path, ...],
) -> CompanySnapshotManifest:
    _ = canonical_workspace_id(workspace_id)
    resolved = database.resolve(strict=False)
    if (
        not database.is_absolute()
        or database.is_symlink()
        or not database.is_file()
        or any(resolved.is_relative_to(root.resolve(strict=False)) for root in personal_roots)
    ):
        raise CompanyMemoryError("COMPANY_SNAPSHOT_SCOPE_DENIED")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0)) as store:
        _ = store.execute("BEGIN")
        tables = cast(
            list[tuple[str]],
            store.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
        )
        if {row[0] for row in tables} != {
            "company_memory_candidates",
            "company_memory_receipts",
        }:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_STORE_REQUIRED")
        for table, columns in (
            ("company_memory_candidates", _CANDIDATE_COLUMNS),
            ("company_memory_receipts", _RECEIPT_COLUMNS),
        ):
            metadata = cast(
                list[tuple[int, str, str, int, str | None, int]],
                store.execute(f"PRAGMA table_info({table})").fetchall(),
            )
            if tuple(row[1] for row in metadata) != columns:
                raise CompanyMemoryError("COMPANY_SNAPSHOT_STORE_REQUIRED")
        try:
            candidates = cast(
                list[CandidateRow],
                store.execute(
                    f"SELECT {','.join(_CANDIDATE_COLUMNS)} FROM company_memory_candidates "
                    + "ORDER BY workspace_id,candidate_id"
                ).fetchall(),
            )
            receipts = cast(
                list[SnapshotReceiptRow],
                store.execute(
                    f"SELECT {','.join(_RECEIPT_COLUMNS)} FROM company_memory_receipts "
                    + "ORDER BY workspace_id,request_digest"
                ).fetchall(),
            )
        except sqlite3.Error as exc:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_STORE_REQUIRED") from exc
        if any(row[0] != workspace_id for row in candidates + receipts):
            raise CompanyMemoryError("COMPANY_SNAPSHOT_WORKSPACE_DENIED")
        keys = {(row[0], row[1]) for row in candidates}
        if any((row[0], row[5]) not in keys for row in receipts):
            raise CompanyMemoryError("COMPANY_SNAPSHOT_RECEIPT_ORPHAN")
        sources: dict[str, CompanySourceBinding] = {}
        for row in candidates:
            arguments: JsonObject = {
                "source_system": row[2],
                "source_locator": row[3],
                "source_event_id": row[4],
                "content_digest": row[6],
                "parser_version": row[7],
            }
            content = resolve_company_source(
                profile, arguments, [str(root) for root in personal_roots]
            )
            if content != row[5]:
                raise CompanyMemoryError("COMPANY_SNAPSHOT_INTEGRITY_FAILED")
            sources[row[3]] = profile.bindings[row[3]]
        reconciliation = hashlib.sha256("\n".join(store.iterdump()).encode()).hexdigest()
    return CompanySnapshotManifest(
        schema_version=1,
        workspace_id=workspace_id,
        database_sha256=_file_digest(database),
        reconciliation_sha256=reconciliation,
        candidates=[dict(zip(_CANDIDATE_COLUMNS, row, strict=True)) for row in candidates],
        receipts=[dict(zip(_RECEIPT_COLUMNS, row, strict=True)) for row in receipts],
        sources=sources,
    )


def _same_entry(descriptor: int, name: str, identity: os.stat_result) -> bool:
    try:
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino)


@contextmanager
def _target_directory(
    directory: Path, personal_roots: tuple[Path, ...], *, create: bool
) -> Generator[tuple[int, dict[str, os.stat_result]]]:
    resolved = directory.resolve(strict=False)
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or any(resolved.is_relative_to(root.resolve(strict=False)) for root in personal_roots)
    ):
        raise CompanyMemoryError("COMPANY_SNAPSHOT_SCOPE_DENIED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open(directory.parent, flags)
    descriptor: int | None = None
    identity: os.stat_result | None = None
    owned: dict[str, os.stat_result] = {}
    complete = False
    try:
        if create:
            os.mkdir(directory.name, mode=0o700, dir_fd=parent)
        identity = os.stat(directory.name, dir_fd=parent, follow_symlinks=False)
        descriptor = os.open(directory.name, flags, dir_fd=parent)
        if os.fstat(descriptor) != identity:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_TARGET_CHANGED")
        if create:
            os.fchmod(descriptor, 0o700)
        yield descriptor, owned
        if not _same_entry(parent, directory.name, identity) or any(
            not _same_entry(descriptor, name, entry) for name, entry in owned.items()
        ):
            raise CompanyMemoryError("COMPANY_SNAPSHOT_TARGET_CHANGED")
        complete = True
    finally:
        try:
            if not complete:
                if descriptor is not None:
                    for name, entry in owned.items():
                        if _same_entry(descriptor, name, entry):
                            os.unlink(name, dir_fd=descriptor)
                if (
                    create
                    and identity is not None
                    and _same_entry(parent, directory.name, identity)
                    and (descriptor is None or not os.listdir(descriptor))
                ):
                    os.rmdir(directory.name, dir_fd=parent)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)


@contextmanager
def _created_file(directory: int, name: str, owned: dict[str, os.stat_result]) -> Generator[int]:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        owned[name] = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)
        yield descriptor
        if not _same_entry(directory, name, owned[name]):
            raise CompanyMemoryError("COMPANY_SNAPSHOT_TARGET_CHANGED")
    finally:
        os.close(descriptor)


def _write_bytes(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise OSError("snapshot write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def create_company_snapshot(
    source_path: Path,
    artifact_directory: Path,
    *,
    workspace_id: str,
    profile: CompanySourceProfile,
    personal_roots: tuple[Path, ...],
) -> CompanySnapshotResult:
    """Create a data-only artifact; originals stay independently pinned outside it."""
    _ = _inventory(source_path, workspace_id, profile, personal_roots)
    with _target_directory(artifact_directory, personal_roots, create=True) as (directory, owned):
        database = Path(f"/proc/self/fd/{directory}/company.db")
        _copy_database(source_path, directory, "company.db", owned)
        manifest = _inventory(database, workspace_id, profile, personal_roots)
        payload = canonical_bytes(cast(JsonObject, manifest.model_dump(mode="json")))
        if len(payload) > 1_048_576:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_MANIFEST_TOO_LARGE")
        with _created_file(directory, "manifest.json", owned) as output:
            _write_bytes(output, payload)
        return manifest.result("created", hashlib.sha256(payload).hexdigest())


def verify_company_snapshot(
    artifact_directory: Path,
    destination: Path,
    *,
    expected_manifest_sha256: str,
    workspace_id: str,
    profile: CompanySourceProfile,
    personal_roots: tuple[Path, ...],
) -> CompanySnapshotResult:
    """Reconcile a caller-pinned artifact in a new target, never restore authority."""
    files = (artifact_directory / "company.db", artifact_directory / "manifest.json")
    resolved = artifact_directory.resolve(strict=False)
    if (
        not artifact_directory.is_absolute()
        or artifact_directory.is_symlink()
        or any(resolved.is_relative_to(root.resolve(strict=False)) for root in personal_roots)
        or artifact_directory.stat().st_mode & 0o777 != 0o700
        or {path.name for path in artifact_directory.iterdir()} != {"company.db", "manifest.json"}
        or any(
            path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o600
            for path in files
        )
    ):
        raise CompanyMemoryError("COMPANY_SNAPSHOT_PRIVACY_DENIED")
    with files[1].open("rb") as source:
        payload = source.read(1_048_577)
    if len(payload) > 1_048_576 or hashlib.sha256(payload).hexdigest() != expected_manifest_sha256:
        raise CompanyMemoryError("COMPANY_SNAPSHOT_PIN_MISMATCH")
    try:
        manifest = CompanySnapshotManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise CompanyMemoryError("COMPANY_SNAPSHOT_MANIFEST_INVALID") from exc
    if manifest.workspace_id != workspace_id:
        raise CompanyMemoryError("COMPANY_SNAPSHOT_WORKSPACE_DENIED")
    actual = _inventory(files[0], workspace_id, profile, personal_roots)
    if actual != manifest:
        raise CompanyMemoryError("COMPANY_SNAPSHOT_INTEGRITY_FAILED")
    with _target_directory(destination, personal_roots, create=True) as (directory, owned):
        recovered = Path(f"/proc/self/fd/{directory}/company.db")
        _copy_database(files[0], directory, "company.db", owned)
        verified = _inventory(recovered, workspace_id, profile, personal_roots)
        if verified.reconciliation_sha256 != manifest.reconciliation_sha256:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_INTEGRITY_FAILED")
        return manifest.result("verified", expected_manifest_sha256)


def snapshot_company_memory(
    source_path: Path,
    destination: Path,
    *,
    personal_roots: tuple[Path, ...],
) -> None:
    """Copy only a company store to a new private target and reconcile all rows."""
    source = source_path.resolve(strict=True)
    target_path = destination.resolve(strict=False)
    if (
        not source_path.is_absolute()
        or not destination.is_absolute()
        or source_path.is_symlink()
        or destination.is_symlink()
        or source == target_path
        or any(
            source.is_relative_to(root.resolve(strict=False))
            or target_path.is_relative_to(root.resolve(strict=False))
            for root in personal_roots
        )
    ):
        raise CompanyMemoryError("COMPANY_SNAPSHOT_SCOPE_DENIED")
    with _target_directory(destination.parent, personal_roots, create=False) as (directory, owned):
        _copy_database(source, directory, destination.name, owned)


def _copy_database(
    source: Path, directory: int, name: str, owned: dict[str, os.stat_result]
) -> None:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=0)) as original:
        _ = original.execute("BEGIN")
        tables = cast(
            list[tuple[str]],
            original.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
        )
        if {row[0] for row in tables} != {
            "company_memory_candidates",
            "company_memory_receipts",
        }:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_STORE_REQUIRED")
        if original.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise CompanyMemoryError("COMPANY_SNAPSHOT_INTEGRITY_FAILED")
        expected = tuple(original.iterdump())
        with _created_file(directory, name, owned) as created:
            with closing(sqlite3.connect(":memory:", timeout=0)) as recovered:
                original.backup(recovered, sleep=0.0)
                if (
                    recovered.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                    or recovered.execute("PRAGMA foreign_key_check").fetchall()
                    or tuple(recovered.iterdump()) != expected
                ):
                    raise CompanyMemoryError("COMPANY_SNAPSHOT_INTEGRITY_FAILED")
                payload = recovered.serialize()
            if not _same_entry(directory, name, owned[name]):
                raise CompanyMemoryError("COMPANY_SNAPSHOT_TARGET_CHANGED")
            _write_bytes(created, payload)
