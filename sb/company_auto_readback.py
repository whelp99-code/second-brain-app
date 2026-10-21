"""Independently verify original auto authority, scoped source and payload spans."""

from __future__ import annotations

import hashlib
import sqlite3

from pydantic import Field, TypeAdapter

from sb.company_approver_binding import decode_key, public_key_fingerprint
from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    assessment_digest,
    command_digest,
    verify_policy_receipt,
)
from sb.company_auto_settings import SourceContext, source_context_digest
from sb.company_db_freshness_models import (
    EvidenceRejected,
    FreshnessRegistry,
    RegistryAutoPolicyPin,
)
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_classifier import CLASSIFIER_VERSION, classify_mail_candidate
from sb.company_internal_effects import candidate_result
from sb.company_memory import MemoryCandidate
from sb.effect_values import JsonObject, canonical_bytes, strict_loads
from sb.effect_write_models import ClosedModel

_CANDIDATE = TypeAdapter[MemoryCandidate](MemoryCandidate)


class _Assessment(ClosedModel):
    classification: str
    reasons: list[str]
    payload: JsonObject
    classifier_version: str


class _Span(ClosedModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class _Payload(ClosedModel):
    schema_version: int
    record_kind: str
    fields: dict[str, str]
    spans: dict[str, _Span]


def verify_auto_authority(
    db: sqlite3.Connection,
    registry: FreshnessRegistry,
    scope: FreshnessScope,
    request_id: str,
    candidate_id: str,
) -> None:
    scope_pins = [
        pin
        for pin in registry.scopes
        if pin.provider_instance_id == scope.provider_instance_id
        and pin.workspace_id == scope.workspace_id
    ]
    rows: list[tuple[str, str]] = db.execute(
        """SELECT receipt_json,auto_command_json FROM company_auto_policy_receipts
        WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
        (scope.provider_instance_id, scope.workspace_id, request_id),
    ).fetchall()
    if len(scope_pins) != 1 or len(rows) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    pin = scope_pins[0]
    if pin.source_deletion_sequence is None or pin.source_deletion_root is None:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    candidate = _CANDIDATE.validate_json(
        canonical_bytes(
            candidate_result(
                db,
                scope.workspace_id,
                candidate_id,
                (pin.source_deletion_sequence, pin.source_deletion_root),
            )
        ),
        strict=True,
    )
    manifests: list[tuple[str]] = db.execute(
        """SELECT manifest_json FROM company_internal_effects
        WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
        (scope.provider_instance_id, scope.workspace_id, request_id),
    ).fetchall()
    if len(manifests) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    manifest = strict_loads(manifests[0][0], 1_048_576)
    if not isinstance(manifest, dict):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    identity = SourceContext.model_validate(manifest.get("source_context"), strict=True)
    receipt = PolicyAutoReceiptV1.model_validate_json(rows[0][0], strict=True)
    command = strict_loads(rows[0][1], 1_048_576)
    if (
        source_context_digest(scope.provider_instance_id, identity) != pin.source_context_digest
        or identity.workspace_id != scope.workspace_id
        or identity.owner != candidate.access.owner
        or not set(candidate.access.projects) <= set(identity.projects)
        or identity.policy_revision != candidate.access.policy_revision
        or identity.deletion_sequence != candidate.deletion_sequence
        or identity.deletion_set_root != candidate.deletion_set_root
        or not isinstance(command, dict)
        or command_digest(command) != receipt.command_digest
        or receipt.scope != scope
        or receipt.candidate_id != candidate_id
        or receipt.auto_request_id != request_id
        or receipt.source_event_id != candidate.source_event_id
        or receipt.content_digest != candidate.content_digest
        or "sha256:" + hashlib.sha256(candidate.content.encode()).hexdigest()
        != candidate.content_digest
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    keys: list[tuple[str]] = db.execute(
        """SELECT json_extract(l.record_json,'$.pin') FROM company_freshness_log l
        JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.phase='registry'
          AND json_extract(l.record_json,'$.kind')='internal_auto_policy'
          AND json_extract(l.record_json,'$.pin.policy_digest')=?
        ORDER BY l.global_sequence""",
        (scope.provider_instance_id, scope.workspace_id, receipt.policy_digest),
    ).fetchall()
    verified = False
    for (raw,) in keys:
        registered = RegistryAutoPolicyPin.model_validate_json(raw, strict=True)
        key = decode_key(registered.public_key)
        if (
            registered.scope != scope
            or public_key_fingerprint(key) != registered.public_key_fingerprint
        ):
            raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
        try:
            verify_policy_receipt(receipt, key)
        except ValueError:
            continue
        verified = True
        break
    if not verified:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    payload = verified_auto_assessment(db, scope, candidate, receipt, command)
    field_values: JsonObject = dict(payload.fields)
    records: list[tuple[str]] = db.execute(
        """SELECT r.payload_json FROM company_internal_records r
        JOIN company_internal_effects e ON e.provider_instance_id=r.provider_instance_id
          AND e.workspace_id=r.workspace_id AND e.operation_id=r.effect_operation_id
        WHERE e.provider_instance_id=? AND e.workspace_id=? AND e.auto_request_id=?""",
        (scope.provider_instance_id, scope.workspace_id, request_id),
    ).fetchall()
    if len(records) != 1 or strict_loads(records[0][0], 1_048_576) != field_values:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")


def verified_auto_assessment(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    candidate: MemoryCandidate,
    receipt: PolicyAutoReceiptV1,
    command: JsonObject,
) -> _Payload:
    """Verify original assessment bytes; never reclassify a retired version.

    Receipt signature/acceptance authority is verified separately by the caller.
    Both accepted resumption and completed-effect readback use this same check.
    """
    candidate_id = candidate.candidate_id
    if (
        receipt.scope != scope
        or receipt.candidate_id != candidate_id
        or receipt.source_event_id != candidate.source_event_id
        or receipt.content_digest != candidate.content_digest
        or "sha256:" + hashlib.sha256(candidate.content.encode()).hexdigest()
        != candidate.content_digest
        or command_digest(command) != receipt.command_digest
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    assessments: list[tuple[str]] = db.execute(
        """SELECT json_object('classification',classification,'reasons',json(reason_codes_json),
        'payload',json(typed_payload_json),'classifier_version',classifier_version)
        FROM company_auto_assessments
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?
          AND content_digest=? AND policy_digest=? AND assessment_digest=?""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            candidate_id,
            candidate.content_digest,
            receipt.policy_digest,
            receipt.assessment_digest,
        ),
    ).fetchall()
    if len(assessments) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    assessment = _Assessment.model_validate_json(assessments[0][0], strict=True)
    if (
        assessment.classification != "auto_internal"
        or assessment.reasons
        or assessment.classifier_version != receipt.classifier_version
        or assessment_digest(
            candidate_id=candidate_id,
            content_digest=candidate.content_digest,
            policy_digest_value=receipt.policy_digest,
            classification=assessment.classification,
            reason_codes=tuple(assessment.reasons),
            payload=assessment.payload,
            classifier_version=assessment.classifier_version,
        )
        != receipt.assessment_digest
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    payload = _Payload.model_validate(assessment.payload, strict=True)
    # Even retired classifier versions retain source-byte and typed-effect
    # integrity checks. Only their historical classification decision is trusted
    # to the already verified, registered policy signature above.
    if (
        payload.schema_version != 1
        or payload.record_kind not in {"contact", "calendar", "progress"}
        or command.get("record_kind") != payload.record_kind
        or not payload.fields
        or payload.fields.keys() != payload.spans.keys()
        or any(
            not 0 <= span.start < span.end <= len(candidate.content)
            or candidate.content[span.start : span.end] != payload.fields[key]
            for key, span in payload.spans.items()
        )
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    if receipt.classifier_version == CLASSIFIER_VERSION:
        classified = classify_mail_candidate(candidate)
        expected: JsonObject = {
            "schema_version": 1,
            "record_kind": classified.record_kind,
            "fields": dict(classified.fields),
            "spans": {
                key: {"start": span.start, "end": span.end}
                for key, span in classified.spans.items()
            },
        }
        if classified.classification != "auto_internal" or expected != assessment.payload:
            raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    return payload
