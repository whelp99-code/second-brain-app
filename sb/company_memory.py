"""Company-memory candidate flow, kept independent from personal memory.

Mail and CWOS integrations may submit sourced candidates here.  Acceptance is
durable and distinct from processing completion; neither transition writes the
CRM or sends mail.  Reads require the current source scope and deletion
high-water, so an old candidate cannot bypass the scoped-memory fence.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sb.effect_values import format_instant
from sb.source_access import SourceAccess


class CompanyMemoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
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
    processed_at: str | None


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_scope(access: SourceAccess, current: SourceAccess) -> None:
    if (
        access.owner != current.owner
        or access.policy_revision != current.policy_revision
        or (not access.projects and bool(current.projects))
        or not set(access.projects) <= set(current.projects)
    ):
        raise CompanyMemoryError("MEMORY_SCOPED_CANDIDATE_DENIED")


class CompanyMemoryStore:
    """Small additive store for sourced company candidates."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS company_memory_candidates (
                candidate_id TEXT PRIMARY KEY,
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
                state TEXT NOT NULL CHECK (state IN ('candidate','accepted','processed_complete','rejected')),
                accepted_at TEXT,
                processed_at TEXT
            )"""
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def receive(
        self,
        *,
        candidate_id: str,
        source_system: str,
        source_locator: str,
        source_event_id: str,
        content: str,
        parser_version: str,
        locator: dict[str, str | int],
        access: SourceAccess,
        deletion: tuple[int, str],
    ) -> MemoryCandidate:
        if not candidate_id or not source_system or not source_locator or not source_event_id:
            raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
        if not content or not parser_version or deletion[0] < 0:
            raise CompanyMemoryError("MEMORY_CANDIDATE_INVALID")
        digest = _digest(content)
        encoded_projects = json.dumps(access.projects, separators=(",", ":"))
        row = self.db.execute(
            "SELECT content_digest,state FROM company_memory_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if row is not None:
            if row[0] != digest:
                raise CompanyMemoryError("MEMORY_CANDIDATE_CONFLICT")
            return self.get(candidate_id, access, deletion)
        self.db.execute(
            """INSERT INTO company_memory_candidates
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (candidate_id, source_system, source_locator, source_event_id, content, digest,
             parser_version, json.dumps(locator, sort_keys=True, separators=(",", ":")),
             access.owner, encoded_projects, access.policy_revision, deletion[0], deletion[1],
             "candidate", None, None),
        )
        self.db.commit()
        return self.get(candidate_id, access, deletion)

    def accept(self, candidate_id: str, current: SourceAccess, deletion: tuple[int, str]) -> MemoryCandidate:
        candidate = self.get(candidate_id, current, deletion)
        _validate_scope(candidate.access, current)
        now = format_instant(datetime.now(UTC))
        self.db.execute(
            "UPDATE company_memory_candidates SET state='accepted',accepted_at=COALESCE(accepted_at,?) "
            "WHERE candidate_id=? AND state='candidate'",
            (now, candidate_id),
        )
        self.db.commit()
        return self.get(candidate_id, current, deletion)

    def mark_processed(self, candidate_id: str, current: SourceAccess, deletion: tuple[int, str]) -> MemoryCandidate:
        candidate = self.get(candidate_id, current, deletion)
        if candidate.state not in {"accepted", "processed_complete"}:
            raise CompanyMemoryError("MEMORY_CANDIDATE_NOT_ACCEPTED")
        now = format_instant(datetime.now(UTC))
        self.db.execute(
            "UPDATE company_memory_candidates SET state='processed_complete',processed_at=COALESCE(processed_at,?) WHERE candidate_id=?",
            (now, candidate_id),
        )
        self.db.commit()
        return self.get(candidate_id, current, deletion)

    def get(self, candidate_id: str, current: SourceAccess, deletion: tuple[int, str]) -> MemoryCandidate:
        row = self.db.execute("SELECT * FROM company_memory_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise CompanyMemoryError("MEMORY_CANDIDATE_NOT_FOUND")
        if (row[11], row[12]) != deletion:
            raise CompanyMemoryError("MEMORY_TOMBSTONE_FENCE_REQUIRED")
        access = SourceAccess(row[8], tuple(json.loads(row[9])), row[10])
        _validate_scope(access, current)
        return MemoryCandidate(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], json.loads(row[7]), access,
            row[11], row[12], row[13], row[14], row[15]
        )

