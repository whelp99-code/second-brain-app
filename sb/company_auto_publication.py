"""Body-free assessment snapshots committed by the freshness publication log."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Protocol

from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_models import (
    Checkpoint,
    CompanyFreshnessProvider,
    FreshnessScope,
    ReserveProgressResponse,
)
from sb.effect_write_models import ClosedModel


class PublishedAssessment(ClosedModel):
    candidate_id: str
    classification: str
    state: str
    source_event_id: str
    policy_version: int
    processed_at: str | None
    receipt_id: str | None
    reason_codes: list[str]
    record_kind: str | None
    operation_id: str
    assessment_digest: str


class InternalAutoJournal(CompanyFreshnessProvider, Protocol):
    def effect_guard(
        self,
        scope: FreshnessScope,
        operation_id: str,
        reservation: ReserveProgressResponse,
    ) -> AbstractContextManager[None]: ...

    def publish_completed_assessments(
        self, scope: FreshnessScope, expected: Checkpoint
    ) -> Checkpoint: ...

    def require_auto_policy(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None: ...

    def publish_assessment(
        self,
        scope: FreshnessScope,
        assessment_digest: str,
        expected: Checkpoint,
    ) -> Checkpoint: ...


def assessment_snapshot(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    digest: str,
) -> PublishedAssessment:
    rows: list[tuple[str]] = db.execute(
        """SELECT json_object(
          'candidate_id',a.candidate_id,'classification',a.classification,
          'state',CASE WHEN EXISTS(
            SELECT 1 FROM company_internal_pending_finish f
            WHERE f.provider_instance_id=a.provider_instance_id
              AND f.workspace_id=a.workspace_id
              AND json_extract(f.pending_json,'$.candidate_id')=a.candidate_id)
            THEN 'uncertain' ELSE c.state END,
          'source_event_id',c.source_event_id,'policy_version',p.policy_version,
          'processed_at',c.processed_at,
          'receipt_id',(SELECT m.receipt_id FROM company_memory_receipts m
            WHERE m.workspace_id=a.workspace_id AND m.candidate_id=a.candidate_id
              AND m.operation='mark_processed' ORDER BY m.created_at,m.receipt_id LIMIT 1),
          'reason_codes',json(a.reason_codes_json),
          'record_kind',(SELECT r.record_kind FROM company_internal_records r
            WHERE r.provider_instance_id=a.provider_instance_id AND r.workspace_id=a.workspace_id
              AND r.source_event_id=c.source_event_id AND r.source_candidate_id=a.candidate_id
            ORDER BY r.record_id LIMIT 1),
          'operation_id',COALESCE(
            (SELECT e.operation_id FROM company_internal_effects e
              WHERE e.provider_instance_id=a.provider_instance_id
                AND e.workspace_id=a.workspace_id AND e.candidate_id=a.candidate_id),
            'assessment:' || a.assessment_digest),
          'assessment_digest',a.assessment_digest)
        FROM company_auto_assessments a
        JOIN company_memory_candidates c
          ON c.workspace_id=a.workspace_id AND c.candidate_id=a.candidate_id
        JOIN company_auto_policies p
          ON p.provider_instance_id=a.provider_instance_id AND p.workspace_id=a.workspace_id
            AND p.policy_digest=a.policy_digest
        WHERE a.provider_instance_id=? AND a.workspace_id=? AND a.assessment_digest=?""",
        (scope.provider_instance_id, scope.workspace_id, digest),
    ).fetchall()
    if len(rows) != 1:
        raise AutoInternalRejected("ASSESSMENT_EVIDENCE_ABSENT")
    return PublishedAssessment.model_validate_json(rows[0][0], strict=True)
