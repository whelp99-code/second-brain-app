"""Workspace-scoped company candidate store, isolated from personal memory."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sb.company_memory_authority import CompanyOperation, canonical_workspace_id
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant, strict_loads
from sb.source_access import SourceAccess

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RECEIPT_DOMAIN = b"second-brain/company-memory-receipt/v1\0"

type CandidateRow = tuple[
    str, str, str, str, str, str, str, str, str, str, str, str, int, str,
    str, str | None, str | None, str | None,
]
type ReceiptRow = tuple[str, str, str, str, str, str]


class CompanyMemoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    workspace_id: str
    candidate_id: str
    source_system: str
    source_locator: str
    source_event_id: str
    content: str
    content_digest: str
    parser_version: str
    locator: dict[str, str | int]
    access: SourceAccess
    deletion_sequence: int
    deletion_set_root: str
    state: str
    accepted_at: str | None
    rejected_at: str | None
    processed_at: str | None


@dataclass(frozen=True, slots=True)
class CompanyMemoryReceipt:
    receipt_id: str
    receipt_digest: str
    workspace_id: str
    request_digest: str
    operation: str
    candidate_id: str
    result: JsonObject
    created_at: str


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_deletion(deletion: tuple[int, str]) -> None:
    if deletion[0] < 0 or _DIGEST.fullmatch(deletion[1]) is None:
        raise CompanyMemoryError("MEMORY_TOMBSTONE_FENCE_REQUIRED")


def _validate_scope(access: SourceAccess, current: SourceAccess) -> None:
    if (
        access.owner != current.owner
        or access.policy_revision != current.policy_revision
        or (not access.projects and bool(current.projects))
        or not set(access.projects) <= set(current.projects)
    ):
        raise CompanyMemoryError("MEMORY_SCOPED_CANDIDATE_DENIED")


def _candidate_result(candidate: MemoryCandidate) -> JsonObject:
    value = asdict(candidate)
    access = candidate.access
    value["access"] = {
        "owner": access.owner,
        "projects": list(access.projects),
        "policy_revision": access.policy_revision,
    }
    return cast(JsonObject, value)


class CompanyMemoryStore:
    """Company-only SQLite store; callers must verify authority before use."""

    def __init__(self, path: Path) -> None:
        self.db: sqlite3.Connection = sqlite3.connect(path)
        _ = self.db.execute("PRAGMA foreign_keys=ON")
        existing = cast(
            tuple[int] | None,
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_memory_candidates'"
            ).fetchone(),
        )
        if existing is not None:
            column_rows = cast(
                list[tuple[int, str, str, int, object, int]],
                self.db.execute("PRAGMA table_info(company_memory_candidates)").fetchall(),
            )
            columns = {row[1] for row in column_rows}
            if "workspace_id" not in columns or "rejected_at" not in columns:
                self.db.close()
                raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        _ = self.db.executescript(
            """CREATE TABLE IF NOT EXISTS company_memory_candidates (
                workspace_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                source_system TEXT NOT NULL,
                source_locator TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                content TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                locator_json TEXT NOT NULL,
                owner TEXT NOT NULL,
                projects_json TEXT NOT NULL,
                policy_revision TEXT NOT NULL,
                deletion_sequence INTEGER NOT NULL CHECK (deletion_sequence >= 0),
                deletion_set_root TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('candidate','accepted','processed_complete','rejected')
                ),
                accepted_at TEXT,
                rejected_at TEXT,
                processed_at TEXT,
                PRIMARY KEY (workspace_id, candidate_id)
            );
            CREATE TABLE IF NOT EXISTS company_memory_receipts (
                workspace_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                receipt_digest TEXT NOT NULL,
                operation TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, request_digest),
                UNIQUE (receipt_id)
            );
            CREATE INDEX IF NOT EXISTS company_memory_source_event_idx
                ON company_memory_candidates(workspace_id, source_system, source_event_id);
            """
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def receive(
        self,
        *,
        workspace_id: str,
        candidate_id: str,
        source_system: str,
        source_locator: str,
        source_event_id: str,
        content: str,
        parser_version: str,
        locator: dict[str, str | int],
        access: SourceAccess,
        deletion: tuple[int, str],
        _commit: bool = True,
    ) -> MemoryCandidate:
        _ = canonical_workspace_id(workspace_id)
        _validate_deletion(deletion)
        if not candidate_id or not source_system or not source_locator or not source_event_id:
            raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
        if not content or not parser_version:
            raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
        digest = _digest(content)
        locator_json = json.dumps(locator, sort_keys=True, separators=(",", ":"))
        projects_json = json.dumps(access.projects, separators=(",", ":"))
        row = cast(
            CandidateRow | None,
            self.db.execute(
                "SELECT * FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?",
                (workspace_id, candidate_id),
            ).fetchone(),
        )
        immutable = (
            source_system,
            source_locator,
            source_event_id,
            content,
            digest,
            parser_version,
            locator_json,
            access.owner,
            projects_json,
            access.policy_revision,
            deletion[0],
            deletion[1],
        )
        if row is not None:
            if tuple(row[2:14]) != immutable:
                raise CompanyMemoryError("MEMORY_CANDIDATE_CONFLICT")
            return self.get(workspace_id, candidate_id, access, deletion)
        _ = self.db.execute(
            """INSERT INTO company_memory_candidates
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                workspace_id,
                candidate_id,
                *immutable,
                "candidate",
                None,
                None,
                None,
            ),
        )
        if _commit:
            self.db.commit()
        return self.get(workspace_id, candidate_id, access, deletion)

    def accept(
        self,
        workspace_id: str,
        candidate_id: str,
        current: SourceAccess,
        deletion: tuple[int, str],
        *,
        now: datetime | None = None,
        _commit: bool = True,
    ) -> MemoryCandidate:
        candidate = self.get(workspace_id, candidate_id, current, deletion)
        if candidate.state == "accepted":
            return candidate
        if candidate.state != "candidate":
            raise CompanyMemoryError("MEMORY_CANDIDATE_TRANSITION_DENIED")
        timestamp = format_instant(now or datetime.now(UTC))
        _ = self.db.execute(
            """UPDATE company_memory_candidates
               SET state='accepted',accepted_at=?
               WHERE workspace_id=? AND candidate_id=? AND state='candidate'""",
            (timestamp, workspace_id, candidate_id),
        )
        if _commit:
            self.db.commit()
        return self.get(workspace_id, candidate_id, current, deletion)

    def reject(
        self,
        workspace_id: str,
        candidate_id: str,
        current: SourceAccess,
        deletion: tuple[int, str],
        *,
        now: datetime | None = None,
        _commit: bool = True,
    ) -> MemoryCandidate:
        candidate = self.get(workspace_id, candidate_id, current, deletion)
        if candidate.state == "rejected":
            return candidate
        if candidate.state != "candidate":
            raise CompanyMemoryError("MEMORY_CANDIDATE_TRANSITION_DENIED")
        timestamp = format_instant(now or datetime.now(UTC))
        _ = self.db.execute(
            """UPDATE company_memory_candidates
               SET state='rejected',rejected_at=?
               WHERE workspace_id=? AND candidate_id=? AND state='candidate'""",
            (timestamp, workspace_id, candidate_id),
        )
        if _commit:
            self.db.commit()
        return self.get(workspace_id, candidate_id, current, deletion)

    def mark_processed(
        self,
        workspace_id: str,
        candidate_id: str,
        current: SourceAccess,
        deletion: tuple[int, str],
        *,
        now: datetime | None = None,
        _commit: bool = True,
    ) -> MemoryCandidate:
        candidate = self.get(workspace_id, candidate_id, current, deletion)
        if candidate.state == "processed_complete":
            return candidate
        if candidate.state != "accepted":
            raise CompanyMemoryError("MEMORY_CANDIDATE_NOT_ACCEPTED")
        timestamp = format_instant(now or datetime.now(UTC))
        _ = self.db.execute(
            """UPDATE company_memory_candidates
               SET state='processed_complete',processed_at=?
               WHERE workspace_id=? AND candidate_id=? AND state='accepted'""",
            (timestamp, workspace_id, candidate_id),
        )
        if _commit:
            self.db.commit()
        return self.get(workspace_id, candidate_id, current, deletion)

    def get(
        self,
        workspace_id: str,
        candidate_id: str,
        current: SourceAccess,
        deletion: tuple[int, str],
    ) -> MemoryCandidate:
        _ = canonical_workspace_id(workspace_id)
        _validate_deletion(deletion)
        row = cast(
            CandidateRow | None,
            self.db.execute(
                "SELECT * FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?",
                (workspace_id, candidate_id),
            ).fetchone(),
        )
        if row is None:
            raise CompanyMemoryError("MEMORY_CANDIDATE_NOT_FOUND")
        if (row[12], row[13]) != deletion:
            raise CompanyMemoryError("MEMORY_TOMBSTONE_FENCE_REQUIRED")
        projects = cast(list[str], json.loads(row[10]))
        access = SourceAccess(row[9], tuple(projects), row[11])
        _validate_scope(access, current)
        return MemoryCandidate(
            workspace_id=row[0],
            candidate_id=row[1],
            source_system=row[2],
            source_locator=row[3],
            source_event_id=row[4],
            content=row[5],
            content_digest=row[6],
            parser_version=row[7],
            locator=cast(dict[str, str | int], json.loads(row[8])),
            access=access,
            deletion_sequence=row[12],
            deletion_set_root=row[13],
            state=row[14],
            accepted_at=row[15],
            rejected_at=row[16],
            processed_at=row[17],
        )

    def execute(
        self,
        *,
        workspace_id: str,
        request_digest: str,
        operation: CompanyOperation,
        arguments: JsonObject,
        current: SourceAccess,
        deletion: tuple[int, str],
        now: datetime,
    ) -> CompanyMemoryReceipt:
        """Apply one verified operation and persist its receipt atomically."""
        if _DIGEST.fullmatch(request_digest) is None:
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        candidate_id = arguments.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
        _ = self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = cast(
                ReceiptRow | None,
                self.db.execute(
                    """SELECT receipt_id,receipt_digest,operation,candidate_id,result_json,created_at
                       FROM company_memory_receipts
                       WHERE workspace_id=? AND request_digest=?""",
                    (workspace_id, request_digest),
                ).fetchone(),
            )
            if existing is not None:
                if existing[2] != operation or existing[3] != candidate_id:
                    raise CompanyMemoryError("COMPANY_RECEIPT_CONFLICT")
                try:
                    raw_result = strict_loads(existing[4], 1_048_576)
                except ValueError as exc:
                    raise CompanyMemoryError("COMPANY_RECEIPT_CORRUPT") from exc
                if not isinstance(raw_result, dict):
                    raise CompanyMemoryError("COMPANY_RECEIPT_CORRUPT")
                replay_body: JsonObject = {
                    "schema_version": 1,
                    "workspace_id": workspace_id,
                    "request_digest": request_digest,
                    "operation": operation,
                    "candidate_id": candidate_id,
                    "result": raw_result,
                    "created_at": existing[5],
                }
                observed = "sha256:" + hashlib.sha256(
                    _RECEIPT_DOMAIN + canonical_bytes(replay_body)
                ).hexdigest()
                if existing[1] != observed or existing[0] != (
                    "cmreceipt:v1:" + observed.removeprefix("sha256:")
                ):
                    raise CompanyMemoryError("COMPANY_RECEIPT_CORRUPT")
                self.db.commit()
                return CompanyMemoryReceipt(
                    existing[0], existing[1], workspace_id, request_digest, operation,
                    candidate_id, raw_result, existing[5],
                )
            if operation == "receive":
                candidate = self.receive(
                    workspace_id=workspace_id,
                    candidate_id=candidate_id,
                    source_system=_required_text(arguments, "source_system"),
                    source_locator=_required_text(arguments, "source_locator"),
                    source_event_id=_required_text(arguments, "source_event_id"),
                    content=_required_text(arguments, "content"),
                    parser_version=_required_text(arguments, "parser_version"),
                    locator=_locator(arguments.get("locator")),
                    access=current,
                    deletion=deletion,
                    _commit=False,
                )
            elif operation == "read":
                candidate = self.get(workspace_id, candidate_id, current, deletion)
            elif operation == "accept":
                candidate = self.accept(
                    workspace_id, candidate_id, current, deletion, now=now, _commit=False
                )
            elif operation == "reject":
                candidate = self.reject(
                    workspace_id, candidate_id, current, deletion, now=now, _commit=False
                )
            else:
                candidate = self.mark_processed(
                    workspace_id, candidate_id, current, deletion, now=now, _commit=False
                )
            result = _candidate_result(candidate)
            created_at = format_instant(now)
            receipt_body: JsonObject = {
                "schema_version": 1,
                "workspace_id": workspace_id,
                "request_digest": request_digest,
                "operation": operation,
                "candidate_id": candidate_id,
                "result": result,
                "created_at": created_at,
            }
            receipt_digest = "sha256:" + hashlib.sha256(
                _RECEIPT_DOMAIN + canonical_bytes(receipt_body)
            ).hexdigest()
            receipt_id = "cmreceipt:v1:" + receipt_digest.removeprefix("sha256:")
            result_json = canonical_bytes(result).decode("utf-8")
            _ = self.db.execute(
                """INSERT INTO company_memory_receipts
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    workspace_id,
                    request_digest,
                    receipt_id,
                    receipt_digest,
                    operation,
                    candidate_id,
                    result_json,
                    created_at,
                ),
            )
            self.db.commit()
            return CompanyMemoryReceipt(
                receipt_id,
                receipt_digest,
                workspace_id,
                request_digest,
                operation,
                candidate_id,
                result,
                created_at,
            )
        except Exception:
            self.db.rollback()
            raise


def _required_text(arguments: JsonObject, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
    return value


def _locator(value: JsonValue | None) -> dict[str, str | int]:
    if not isinstance(value, dict) or not all(
        isinstance(item, (str, int)) and not isinstance(item, bool)
        for item in value.values()
    ):
        raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
    return cast(dict[str, str | int], value)
