"""Repeat policy, claim and original source validation inside the SQL effect writer."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Literal

from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    policy_digest,
    receipt_expired,
    verify_policy_receipt,
)
from sb.company_auto_recovery import AcceptedAutoAuthority, accepted_auto_authority
from sb.company_auto_settings import AutoInternalContext, AutoInternalRejected, AutoInternalSettings
from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_effects import memory_request_digest
from sb.company_memory import MemoryCandidate
from sb.effect_values import format_instant, strict_loads


def require_auto_transaction(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    candidate: MemoryCandidate,
    request_id: str,
    command_digest: str,
    operation: Literal["accept", "complete", "mark_processed"],
    *,
    continuation: AcceptedAutoAuthority | None = None,
) -> None:
    if continuation:
        if operation == "accept":
            raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
        original = accepted_auto_authority(db, scope, candidate.candidate_id)
        if (
            policy_digest(original.policy) != policy_digest(settings.policy)
            or original.public_key.public_bytes_raw() != continuation.public_key.public_bytes_raw()
        ):
            raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    rows: list[
        tuple[
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            int,
            str,
            str,
        ]
    ] = db.execute(
        """SELECT source_system,source_event_id,source_locator,content,content_digest,parser_version,
        locator_json,owner,projects_json,policy_revision,deletion_sequence,deletion_set_root,state
        FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?""",
        (scope.workspace_id, candidate.candidate_id),
    ).fetchall()
    if len(rows) != 1:
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    row = rows[0]
    if (
        row[:6]
        != (
            "mail",
            candidate.source_event_id,
            candidate.source_locator,
            candidate.content,
            candidate.content_digest,
            candidate.parser_version,
        )
        or strict_loads(row[6], 65_536) != candidate.locator
        or row[7] != context.owner
        or strict_loads(row[8], 65_536) != list(candidate.access.projects)
        or not set(candidate.access.projects) <= set(context.projects)
        or row[9:12]
        != (context.policy_revision, context.deletion_sequence, context.deletion_set_root)
        or row[12] != ("candidate" if operation == "accept" else "accepted")
        or "sha256:" + hashlib.sha256(row[3].encode()).hexdigest() != row[4]
    ):
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    claims: list[tuple[str, str, str]] = db.execute(
        """SELECT path,workflow_request_id,content_digest FROM company_candidate_execution_claims
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?""",
        (scope.provider_instance_id, scope.workspace_id, candidate.candidate_id),
    ).fetchall()
    if claims != [("auto_internal", request_id, candidate.content_digest)]:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if operation != "accept":
        accepted_digest = memory_request_digest("accept", candidate.candidate_id, request_id)
        accepted: list[tuple[str]] = db.execute(
            """SELECT receipt_digest FROM company_memory_receipts
            WHERE workspace_id=? AND request_digest=? AND operation='accept' AND candidate_id=?""",
            (scope.workspace_id, accepted_digest, candidate.candidate_id),
        ).fetchall()
        if len(accepted) != 1:
            raise AutoInternalRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        _ = verify_memory_receipt(db, scope, "accept", accepted_digest, accepted[0][0])
    originals: list[tuple[str]] = db.execute(
        """SELECT receipt_json FROM company_auto_policy_receipts
        WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
        (scope.provider_instance_id, scope.workspace_id, request_id),
    ).fetchall()
    if len(originals) != 1:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    receipt = PolicyAutoReceiptV1.model_validate_json(originals[0][0], strict=True)
    verify_policy_receipt(
        receipt, continuation.public_key if continuation is not None else settings.signer.public_key
    )
    if (
        receipt.scope != scope
        or receipt.auto_request_id != request_id
        or receipt.candidate_id != candidate.candidate_id
        or receipt.content_digest != candidate.content_digest
        or receipt.source_event_id != candidate.source_event_id
        or receipt.command_digest != command_digest
        or receipt.policy_digest != policy_digest(settings.policy)
        or (not continuation and receipt.policy_digest in settings.revoked_policy_digests)
        or operation not in receipt.allowed_operations
        or (operation == "accept" and receipt_expired(receipt, format_instant(context.now)))
    ):
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
