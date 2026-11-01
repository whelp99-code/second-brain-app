"""Read-only authority for completing an already anchored automatic acceptance.

Revocation forbids new acceptance, not replay of the original accepted command.
No historical private key is loaded and no replacement policy receipt is issued.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.company_approver_binding import decode_key, public_key_fingerprint
from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    auto_request_id,
    command_digest,
    policy_digest,
    verify_policy_receipt,
)
from sb.company_auto_settings import AutoInternalRejected, InternalAutoPolicyV1
from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_db_freshness_hash import operation_id_for
from sb.company_db_freshness_models import RegistryAutoPolicyPin
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_effects import human_path_blocks, memory_request_digest
from sb.effect_values import parse_instant, strict_loads


@dataclass(frozen=True, slots=True)
class AcceptedAutoAuthority:
    policy: InternalAutoPolicyV1
    public_key: Ed25519PublicKey


def accepted_auto_authority(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    candidate_id: str,
) -> AcceptedAutoAuthority:
    """Caller must first recover/verify the provider's anchor under its guard."""
    rows: list[tuple[str, str, str, str]] = db.execute(
        """SELECT r.receipt_json,r.auto_command_json,p.policy_json,c.content_digest
        FROM company_auto_policy_receipts r
        JOIN company_candidate_execution_claims c
          ON c.provider_instance_id=r.provider_instance_id AND c.workspace_id=r.workspace_id
          AND c.candidate_id=r.candidate_id AND c.content_digest=r.content_digest
          AND c.path='auto_internal' AND c.workflow_request_id=r.auto_request_id
        JOIN company_auto_policies p
          ON p.provider_instance_id=r.provider_instance_id AND p.workspace_id=r.workspace_id
          AND p.policy_digest=r.policy_digest
        WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?""",
        (scope.provider_instance_id, scope.workspace_id, candidate_id),
    ).fetchall()
    if len(rows) != 1 or human_path_blocks(db, scope, candidate_id):
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    raw, command_raw, policy_raw, content_digest = rows[0]
    receipt = PolicyAutoReceiptV1.model_validate_json(raw, strict=True)
    policy = InternalAutoPolicyV1.model_validate_json(policy_raw, strict=True)
    command = strict_loads(command_raw, 1_048_576)
    request_id = auto_request_id(scope, candidate_id, content_digest, policy_digest(policy))
    if (
        receipt.scope != scope
        or receipt.candidate_id != candidate_id
        or receipt.content_digest != content_digest
        or receipt.auto_request_id != request_id
        or receipt.policy_digest != policy_digest(policy)
        or receipt.policy_version != policy.policy_version
        or not isinstance(command, dict)
        or receipt.command_digest != command_digest(command)
    ):
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    operation_id = operation_id_for(
        scope, request_id=request_id, command_digest=receipt.command_digest, operation="accept"
    )
    event = memory_request_digest("accept", candidate_id, request_id)
    accepted: list[tuple[str, str, int]] = db.execute(
        """SELECT m.receipt_digest,m.created_at,l.global_sequence FROM company_memory_receipts m
        JOIN company_freshness_operations o
          ON o.provider_instance_id=? AND o.workspace_id=m.workspace_id
          AND o.operation_id=? AND o.event_digest=m.request_digest
          AND o.operation='accept' AND o.actor_store='second_brain'
          AND o.state='finished' AND o.terminal_state='accepted'
          AND o.evidence_digest=m.receipt_digest
        JOIN company_freshness_log l
          ON l.provider_instance_id=o.provider_instance_id AND l.workspace_id=o.workspace_id
          AND l.operation_id=o.operation_id AND l.phase='reserve'
          AND json_extract(l.record_json,'$.reservation_id')=o.reservation_id
        JOIN company_freshness_publication f ON f.global_sequence=l.global_sequence
        WHERE m.workspace_id=? AND m.candidate_id=? AND m.operation='accept'
          AND m.request_digest=?""",
        (scope.provider_instance_id, operation_id, scope.workspace_id, candidate_id, event),
    ).fetchall()
    if len(accepted) != 1:
        raise AutoInternalRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    digest, created_at, reserved_sequence = accepted[0]
    verify_memory_receipt(db, scope, "accept", event, digest)
    if (
        not parse_instant(receipt.issued_at)
        <= parse_instant(created_at)
        < parse_instant(receipt.expires_at)
    ):
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    # The policy active at the original reservation, not any later re-installation.
    pins: list[tuple[str]] = db.execute(
        """SELECT json_extract(l.record_json,'$.pin') FROM company_freshness_log l
        JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.phase='registry'
          AND json_extract(l.record_json,'$.kind')='internal_auto_policy'
          AND l.global_sequence<? ORDER BY l.global_sequence DESC LIMIT 1""",
        (scope.provider_instance_id, scope.workspace_id, reserved_sequence),
    ).fetchall()
    if len(pins) != 1:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    pin = RegistryAutoPolicyPin.model_validate_json(pins[0][0], strict=True)
    key = decode_key(pin.public_key)
    if (
        pin.scope != scope
        or pin.policy_digest != receipt.policy_digest
        or public_key_fingerprint(key) != pin.public_key_fingerprint
        or receipt.policy_digest in pin.revoked_policy_digests
        or pin.public_key_fingerprint in pin.revoked_key_fingerprints
    ):
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    verify_policy_receipt(receipt, key)
    return AcceptedAutoAuthority(policy, key)
