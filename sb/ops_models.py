"""Typed operational results and stable JSON snapshot shapes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, override


class OperationError(Exception):
    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive: Path
    checksum: str
    files: int
    bytes: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    destination: Path
    files: int
    bytes: int
    previous: Path | None


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: str
    detail: str

    def as_dict(self) -> DoctorCheckSnapshot:
        return {"name": self.name, "status": self.status, "detail": self.detail}


class DoctorCheckSnapshot(TypedDict):
    name: str
    status: str
    detail: str


class RunSnapshot(TypedDict):
    run_id: str
    started_at: str
    finished_at: str | None
    git_commit: str | None
    status: str


class BatchSnapshot(TypedDict):
    run_id: str
    status: str
    started_at: str
    finished_at: str | None
    stages_attempted: int
    written: int
    errors: int


class StageSnapshot(TypedDict):
    run_id: str
    stage: str
    status: str
    errors: int
    error: str
    detail: str


class FailedDerivationSnapshot(TypedDict):
    key: str
    stage: str
    attempts: int
    error: str
    retry_hold_reason: str | None


class PageCounts(TypedDict):
    wiki: int
    daily: int
    conflicts: int


class RawCounts(TypedDict):
    files: int
    bytes: int


class StatusSnapshot(TypedDict):
    vault_root: str
    initialized: bool
    schema_version: int
    schema_current: int
    git_head: str | None
    git_clean: bool
    last_run: RunSnapshot | None
    recent_stages: list[StageSnapshot]
    last_batch: BatchSnapshot | None
    run_counts: dict[str, int]
    derivation_counts: dict[str, int]
    failed_derivations: list[FailedDerivationSnapshot]
    failed_by_stage: dict[str, int]
    failed_details_omitted: int
    pages: PageCounts
    raw: RawCounts


class MigrationSnapshot(TypedDict):
    before: int
    after: int
    current: int
    pending: int
    backup: str | None
