"""Exclude human and automatic execution of the same company candidate."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.effect_values import format_instant


class ExecutionCandidate(Protocol):
    @property
    def workspace_id(self) -> str: ...
    @property
    def candidate_id(self) -> str: ...
    @property
    def content_digest(self) -> str: ...


def claim_human_execution(
    db: sqlite3.Connection,
    candidate: ExecutionCandidate,
    context: CompanyAuthorityContext,
    request_id: str,
    now: datetime,
) -> None:
    """Called inside the handoff transaction when internal-auto is installed."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_candidate_execution_claims'",
    ).fetchone():
        return
    rows: list[tuple[str, str]] = db.execute(
        """SELECT content_digest,path FROM company_candidate_execution_claims
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?""",
        (context.provider, candidate.workspace_id, candidate.candidate_id),
    ).fetchall()
    if rows:
        if rows[0] != (candidate.content_digest, "human"):
            raise CompanyAuthorityRejected("COMPANY_EXECUTION_CLAIM_CONFLICT")
        return
    _ = db.execute(
        """INSERT INTO company_candidate_execution_claims
        (provider_instance_id,workspace_id,candidate_id,content_digest,path,
         workflow_request_id,created_at) VALUES(?,?,?,?,?,?,?)""",
        (
            context.provider, candidate.workspace_id, candidate.candidate_id,
            candidate.content_digest, "human", request_id, format_instant(now),
        ),
    )
