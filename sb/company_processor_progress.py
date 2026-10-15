"""Processor intent ordering and its local, restore-sensitive checkpoint."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import ValidationError

from sb.company_freshness import (
    TERMINAL_STATE_BY_OPERATION,
    Checkpoint,
    CompanyFreshnessProvider,
    FinishProgressRequest,
    FreshnessScope,
    FreshnessWireError,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_values import model_object

type ProcessorOperation = Literal["accept", "reject", "mark_processed"]


def local_checkpoint(
    database: Path,
    workspace_id: str,
    initial: Checkpoint | None,
) -> Checkpoint | None:
    if not database.exists():
        return initial
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
            _ = db.execute("PRAGMA query_only=ON")
            table = cast(
                tuple[int] | None,
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_processor_checkpoint'",
                ).fetchone(),
            )
            if table:
                row = cast(
                    tuple[str] | None,
                    db.execute(
                        "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
                        (workspace_id,),
                    ).fetchone(),
                )
                if row is not None:
                    return Checkpoint.model_validate_json(row[0])
            enrollment = cast(
                tuple[int] | None,
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_handoff_enrollment'",
                ).fetchone(),
            )
            if (
                enrollment
                and db.execute(
                    "SELECT 1 FROM company_handoff_enrollment WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone()
            ):
                raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
    except (sqlite3.Error, ValidationError) as exc:
        raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK") from exc
    return initial


def save_checkpoint(
    db: sqlite3.Connection,
    workspace_id: str,
    checkpoint: Checkpoint,
    expected: Checkpoint | None = None,
) -> None:
    raw = canonical_bytes(model_object(checkpoint)).decode()
    if expected is None:
        _ = db.execute(
            """INSERT INTO company_processor_checkpoint VALUES(?,?)
            ON CONFLICT(workspace_id) DO NOTHING""",
            (workspace_id, raw),
        )
        return
    changed = db.execute(
        """UPDATE company_processor_checkpoint SET checkpoint_json=?
        WHERE workspace_id=? AND checkpoint_json=?""",
        (raw, workspace_id, canonical_bytes(model_object(expected)).decode()),
    )
    if changed.rowcount != 1:
        raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")


def reserve_operation(
    provider: CompanyFreshnessProvider,
    scope: FreshnessScope,
    operation: ProcessorOperation,
    request_id: str,
    command_digest: str,
    event_digest: str,
    expected: Checkpoint,
) -> tuple[str, ReserveProgressResponse]:
    identity: JsonObject = {
        "scope": model_object(scope),
        "request_id": request_id,
        "command_digest": command_digest,
        "operation": operation,
    }
    operation_id = (
        "sha256:"
        + hashlib.sha256(
            b"second-brain/company-operation/v1\0" + canonical_bytes(identity),
        ).hexdigest()
    )
    request = ReserveProgressRequest(
        schema_version=2,
        scope=scope,
        operation_id=operation_id,
        operation=operation,
        expected_checkpoint=expected,
        event_digest=event_digest,
        challenge="reserve:" + uuid4().hex,
    )
    try:
        response = provider.reserve_progress(request)
    except (TimeoutError, OSError) as exc:
        raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
    if isinstance(response, FreshnessWireError):
        raise CompanyAuthorityRejected(response.code)
    if response.scope != scope or response.challenge != request.challenge:
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED")
    if response.outcome == "already_reserved":
        raise CompanyAuthorityRejected("COMPANY_DUPLICATE_OPERATION")
    if response.outcome == "conflict":
        raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
    checkpoint = response.checkpoint
    if (
        checkpoint is None
        or response.reservation_id is None
        or checkpoint.operational_epoch != expected.operational_epoch
        or checkpoint.approval_binding_digest != expected.approval_binding_digest
        or checkpoint.approval_policy_version != expected.approval_policy_version
        or checkpoint.intent_sequence <= expected.intent_sequence
    ):
        raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
    return operation_id, response


def finish_operation(
    provider: CompanyFreshnessProvider,
    operation: ProcessorOperation,
    reservation: ReserveProgressResponse,
    operation_id: str,
    evidence_digest: str,
) -> Checkpoint:
    assert reservation.checkpoint is not None and reservation.reservation_id is not None
    request = FinishProgressRequest(
        schema_version=2,
        scope=reservation.scope,
        operation_id=operation_id,
        reservation_id=reservation.reservation_id,
        expected_checkpoint=reservation.checkpoint,
        evidence_digest=evidence_digest,
        terminal_state=TERMINAL_STATE_BY_OPERATION[operation],
        challenge="finish:" + uuid4().hex,
    )
    try:
        response = provider.finish_progress(request)
    except (TimeoutError, OSError) as exc:
        raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
    if isinstance(response, FreshnessWireError):
        raise CompanyAuthorityRejected(response.code)
    checkpoint = response.checkpoint
    if (
        response.scope != request.scope
        or response.challenge != request.challenge
        or response.outcome == "conflict"
        or checkpoint is None
        or checkpoint.operational_epoch != reservation.checkpoint.operational_epoch
        or checkpoint.approval_binding_digest != reservation.checkpoint.approval_binding_digest
        or checkpoint.approval_policy_version != reservation.checkpoint.approval_policy_version
        or checkpoint.intent_sequence <= reservation.checkpoint.intent_sequence
    ):
        raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
    return checkpoint
