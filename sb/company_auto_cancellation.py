"""Prove an automatic transition unapplied without changing its claim or signed audit."""

from __future__ import annotations

import hashlib
import sqlite3

from sb.company_approver_binding import decode_key, public_key_fingerprint
from sb.company_auto_intents import PendingAutoReserve
from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    auto_request_id,
    command_digest,
    verify_policy_receipt,
)
from sb.company_auto_recovery import accepted_auto_authority
from sb.company_auto_settings import AutoInternalRejected
from sb.company_db_freshness_hash import checkpoint_text, operation_id_for
from sb.company_db_freshness_models import OperationRow, RegistryAutoPolicyPin
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_effects import human_path_blocks, memory_request_digest
from sb.effect_values import JsonObject, strict_loads


def verify_auto_cancellation(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    original: OperationRow,
    record: JsonObject,
) -> None:
    raw = record.get("auto_intent")
    if raw is None:
        return
    intent = PendingAutoReserve.model_validate(raw, strict=True)
    request = intent.request
    rows: list[tuple[str, str, str, str, str, str]] = db.execute(
        """SELECT r.receipt_json,r.auto_command_json,c.content_digest,c.content,c.state,c.source_event_id
        FROM company_auto_policy_receipts r JOIN company_memory_candidates c
          ON c.workspace_id=r.workspace_id AND c.candidate_id=r.candidate_id
          AND c.content_digest=r.content_digest
        JOIN company_candidate_execution_claims w
          ON w.provider_instance_id=r.provider_instance_id AND w.workspace_id=r.workspace_id
          AND w.candidate_id=r.candidate_id AND w.content_digest=r.content_digest
          AND w.path='auto_internal' AND w.workflow_request_id=r.auto_request_id
        WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.auto_request_id=?
          AND r.candidate_id=?""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            intent.auto_request_id,
            intent.candidate_id,
        ),
    ).fetchall()
    if len(rows) != 1:
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    receipt = PolicyAutoReceiptV1.model_validate_json(rows[0][0], strict=True)
    command = strict_loads(rows[0][1], 1_048_576)
    content_digest, content, state, event_id = rows[0][2:]
    if (
        request.scope != scope
        or request.operation not in {"accept", "complete"}
        or original.operation != request.operation
        or original.operation_id != request.operation_id
        or original.reserve_expected_json != checkpoint_text(request.expected_checkpoint)
        or original.event_digest != request.event_digest
        or receipt.scope != scope
        or receipt.candidate_id != intent.candidate_id
        or receipt.content_digest != content_digest
        or state != ("candidate" if request.operation == "accept" else "accepted")
        or receipt.source_event_id != event_id
        or content_digest != "sha256:" + hashlib.sha256(content.encode()).hexdigest()
        or receipt.auto_request_id != intent.auto_request_id
        or auto_request_id(scope, intent.candidate_id, content_digest, receipt.policy_digest)
        != intent.auto_request_id
        or not isinstance(command, dict)
        or command_digest(command) != intent.command_digest
        or receipt.command_digest != intent.command_digest
        or operation_id_for(
            scope,
            request_id=intent.auto_request_id,
            command_digest=intent.command_digest,
            operation=request.operation,
        )
        != original.operation_id
        or memory_request_digest(request.operation, intent.candidate_id, intent.auto_request_id)
        != original.event_digest
        or human_path_blocks(db, scope, intent.candidate_id)
    ):
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    # A cancelled completion retains its original, anchored acceptance, but no completion
    # receipt or effect may exist. Cancellation never authorizes a replacement workflow.
    if request.operation == "complete":
        try:
            accepted_auto_authority(db, scope, intent.candidate_id)
        except AutoInternalRejected as exc:
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
    if db.execute(
        """SELECT 1 FROM company_memory_receipts WHERE workspace_id=? AND candidate_id=?
        AND (?='accept' OR operation!='accept')""",
        (scope.workspace_id, intent.candidate_id, request.operation),
    ).fetchone():
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    # Complete uses another operation ID: prove zero effects across the entire candidate.
    for table, column in (
        ("company_internal_effects", "candidate_id"),
        ("company_internal_records", "source_candidate_id"),
    ):
        if db.execute(
            f"SELECT 1 FROM {table} WHERE workspace_id=? AND {column}=?",
            (scope.workspace_id, intent.candidate_id),
        ).fetchone():
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    if db.execute(
        """SELECT 1 FROM company_internal_pending_finish WHERE workspace_id=?
          AND (json_extract(pending_json,'$.candidate_id')=?
            OR json_extract(pending_json,'$.auto_request_id')=?)""",
        (scope.workspace_id, intent.candidate_id, intent.auto_request_id),
    ).fetchone():
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    # Historical public evidence authorizes cancellation only, never a new acceptance.
    pins: list[tuple[str]] = db.execute(
        """SELECT json_extract(p.record_json,'$.pin') FROM company_freshness_log p
        JOIN company_freshness_publication f ON f.global_sequence=p.global_sequence
        WHERE p.provider_instance_id=? AND p.workspace_id=?
          AND json_extract(p.record_json,'$.kind')='internal_auto_policy'
          AND json_extract(p.record_json,'$.pin.policy_digest')=?
          AND p.global_sequence<(SELECT global_sequence FROM company_freshness_log
            WHERE provider_instance_id=? AND workspace_id=? AND operation_id=? AND phase='reserve')
        ORDER BY p.global_sequence DESC""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            receipt.policy_digest,
            scope.provider_instance_id,
            scope.workspace_id,
            original.operation_id,
        ),
    ).fetchall()
    for (pin_raw,) in pins:
        pin = RegistryAutoPolicyPin.model_validate_json(pin_raw, strict=True)
        key = decode_key(pin.public_key)
        if (
            pin.scope != scope
            or public_key_fingerprint(key) != pin.public_key_fingerprint
            or pin.policy_digest in pin.revoked_policy_digests
            or pin.public_key_fingerprint in pin.revoked_key_fingerprints
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        try:
            verify_policy_receipt(receipt, key)
        except ValueError:
            continue
        return
    raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
