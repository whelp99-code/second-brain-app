"""Finish only the original reservation proved by a committed local receipt."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_approver_binding import CompanyHandoffPolicy, Digest, binding_digest
from sb.company_freshness_models import (
    Checkpoint,
    CompanyFreshnessProvider,
    FreshnessScope,
    ReserveProgressResponse,
)
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.company_memory_handoff import require_enrollment
from sb.company_processor_progress import (
    ProcessorOperation,
    finish_operation,
    save_checkpoint,
)
from sb.effect_values import JsonObject, canonical_bytes, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class PendingFinish(ClosedModel):
    operation: ProcessorOperation
    operation_id: Digest
    reservation: ReserveProgressResponse
    original_reservation_retry: bool = False


def save_pending_finish(
    db: sqlite3.Connection,
    workspace_id: str,
    request_digest: str,
    pending: PendingFinish,
) -> None:
    """Called inside the effect transaction, before its original receipt commits."""
    _ = db.execute(
        "INSERT INTO company_processor_pending_finish VALUES(?,?,?)",
        (workspace_id, request_digest, canonical_bytes(model_object(pending)).decode()),
    )


def resume_pending_finish(
    database: Path,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    provider: CompanyFreshnessProvider,
) -> None:
    """Retry a committed original finish, never reserve or execute a new effect."""
    if not database.exists():
        return
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
        _ = db.execute("PRAGMA query_only=ON")
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_processor_pending_finish'",
        ).fetchone():
            return
        _ = db.execute("BEGIN")
        rows: list[tuple[str, str, str, str, str, str, str, str, str]] = db.execute(
            """SELECT p.pending_json,p.request_digest,r.receipt_id,r.receipt_digest,
                r.operation,r.candidate_id,r.result_json,r.created_at,c.checkpoint_json
            FROM company_processor_pending_finish p
            JOIN company_memory_receipts r
                ON r.workspace_id=p.workspace_id AND r.request_digest=p.request_digest
            JOIN company_processor_checkpoint c ON c.workspace_id=p.workspace_id
            WHERE p.workspace_id=?""",
            (context.workspace_id,),
        ).fetchall()
        if not rows:
            return
        row = rows[0]
        require_enrollment(db, context, policy)
        try:
            pending = PendingFinish.model_validate_json(row[0])
            checkpoint = Checkpoint.model_validate_json(row[8])
            result = strict_loads(row[6], 1_048_576)
        except ValueError as exc:
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
        reservation = pending.reservation
        if (
            (
                reservation.outcome != "reserved"
                and not (
                    reservation.outcome == "already_reserved" and pending.original_reservation_retry
                )
            )
            or reservation.scope
            != FreshnessScope(
                provider_instance_id=context.provider,
                workspace_id=context.workspace_id,
            )
            or reservation.checkpoint != checkpoint
            or checkpoint.approval_policy_version != policy.approval_policy_version
            or checkpoint.approval_binding_digest != binding_digest(context, policy)
            or row[4] != pending.operation
            or not isinstance(result, dict)
        ):
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
        receipt_body: JsonObject = {
            "schema_version": 1,
            "workspace_id": context.workspace_id,
            "request_digest": row[1],
            "operation": row[4],
            "candidate_id": row[5],
            "result": result,
            "created_at": row[7],
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                b"second-brain/company-memory-receipt/v1\0" + canonical_bytes(receipt_body),
            ).hexdigest()
        )
        if row[3] != digest or row[2] != "cmreceipt:v1:" + digest.removeprefix("sha256:"):
            raise CompanyAuthorityRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    finished = finish_operation(
        provider,
        pending.operation,
        reservation,
        pending.operation_id,
        digest,
    )
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=rw", uri=True)) as db, db:
        save_checkpoint(db, context.workspace_id, finished, checkpoint)
        changed = db.execute(
            """DELETE FROM company_processor_pending_finish
            WHERE workspace_id=? AND request_digest=? AND pending_json=?""",
            (context.workspace_id, row[1], row[0]),
        )
        if changed.rowcount != 1:
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
