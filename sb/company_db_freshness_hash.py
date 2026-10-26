"""Domain-separated digests for the company DB freshness ledger."""

from __future__ import annotations

import hashlib
from typing import Final

from sb.company_freshness_models import Checkpoint, FreshnessScope
from sb.effect_values import JsonInput, JsonObject, JsonValue, canonical_bytes

LOG_DOMAIN: Final = b"second-brain/company-db-log/v1\0"
PROGRESS_DOMAIN: Final = b"second-brain/company-db-progress/v1\0"
EVIDENCE_DOMAIN: Final = b"second-brain/company-db-evidence/v1\0"
GENESIS_DOMAIN: Final = b"second-brain/company-db-genesis/v1\0"
GENESIS_STREAM_DOMAIN: Final = b"second-brain/company-db-genesis-stream/v1\0"
OPERATION_DOMAIN: Final = b"second-brain/company-operation/v1\0"
RECEIPT_DOMAIN: Final = b"second-brain/company-memory-receipt/v1\0"
AUTO_RECEIPT_DOMAIN: Final = b"second-brain/company-auto-policy-receipt/v1\0"
EFFECT_DOMAIN: Final = b"second-brain/company-internal-effect/v1\0"
JARVIS_EVIDENCE_DOMAIN: Final = b"second-brain/company-freshness-jarvis-evidence/v1\0"
DELETION_DOMAIN: Final = b"second-brain/company-db-deletion-evidence/v1\0"


def prefixed_digest(domain: bytes, value: JsonInput) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def raw_digest(value: str) -> bytes:
    hex_text = value.removeprefix("sha256:")
    if len(hex_text) != 64 or any(character not in "0123456789abcdef" for character in hex_text):
        raise ValueError("COMPANY_CONTRACT_INVALID")
    return bytes.fromhex(hex_text)


def next_nv(current: bytes, record_digest: str) -> bytes:
    if len(current) != 32:
        raise ValueError("COMPANY_FRESHNESS_REQUIRED")
    return hashlib.sha256(current + raw_digest(record_digest)).digest()


def scope_object(scope: FreshnessScope) -> JsonObject:
    return {
        "provider_instance_id": scope.provider_instance_id,
        "workspace_id": scope.workspace_id,
    }


def checkpoint_object(checkpoint: Checkpoint) -> JsonObject:
    return checkpoint.model_dump(mode="json")


def checkpoint_text(checkpoint: Checkpoint | None) -> str:
    if checkpoint is None:
        return "null"
    return canonical_bytes(checkpoint_object(checkpoint)).decode("utf-8")


def record_digest(
    *,
    global_sequence: int,
    scope: FreshnessScope,
    phase: str,
    record: JsonObject,
    evidence: list[JsonObject],
    before_checkpoint: Checkpoint | None,
    after_checkpoint: Checkpoint,
) -> str:
    evidence_value: list[JsonValue] = []
    evidence_value.extend(evidence)
    body: JsonObject = {
        "global_sequence": global_sequence,
        "scope": scope_object(scope),
        "phase": phase,
        "record": record,
        "evidence": evidence_value,
        "before_checkpoint": None
        if before_checkpoint is None
        else checkpoint_object(before_checkpoint),
        "after_checkpoint": checkpoint_object(after_checkpoint),
    }
    return prefixed_digest(LOG_DOMAIN, body)


def progress_root(previous_root: str, sequence: int, record: JsonObject) -> str:
    return prefixed_digest(
        PROGRESS_DOMAIN,
        {"previous_root": previous_root, "sequence": sequence, "record": record},
    )


def evidence_root(
    scope: FreshnessScope,
    store: str,
    stream: str,
    previous_root: str,
    sequence: int,
    source_record_id: str,
    source_digest: str,
) -> str:
    return prefixed_digest(
        EVIDENCE_DOMAIN,
        {
            "scope": scope_object(scope),
            "store": store,
            "stream": stream,
            "previous_root": previous_root,
            "sequence": sequence,
            "source_record_id": source_record_id,
            "source_digest": source_digest,
        },
    )


def genesis_stream_root(
    scope: FreshnessScope,
    store: str,
    stream: str,
    entries: list[JsonObject],
) -> str:
    listed: list[JsonValue] = []
    listed.extend(entries)
    return prefixed_digest(
        GENESIS_STREAM_DOMAIN,
        {"scope": scope_object(scope), "store": store, "stream": stream, "entries": listed},
    )


def genesis_intent_root(
    scope: FreshnessScope,
    *,
    operational_epoch: int,
    approval_policy_version: int,
    approval_binding_digest: str,
    revocation_sequence: int,
    revocation_root: str,
    stores: JsonObject,
) -> str:
    return prefixed_digest(
        GENESIS_DOMAIN,
        {
            "scope": scope_object(scope),
            "operational_epoch": operational_epoch,
            "approval_policy_version": approval_policy_version,
            "approval_binding_digest": approval_binding_digest,
            "revocation_sequence": revocation_sequence,
            "revocation_root": revocation_root,
            "stores": stores,
        },
    )


def operation_id_for(
    scope: FreshnessScope,
    *,
    request_id: str,
    command_digest: str,
    operation: str,
) -> str:
    return prefixed_digest(
        OPERATION_DOMAIN,
        {
            "scope": scope_object(scope),
            "request_id": request_id,
            "command_digest": command_digest,
            "operation": operation,
        },
    )


def deletion_operation_id(scope: FreshnessScope, deletion_plan_digest: str) -> str:
    return prefixed_digest(
        OPERATION_DOMAIN,
        {
            "scope": scope_object(scope),
            "deletion_plan_digest": deletion_plan_digest,
            "operation": "delete",
        },
    )


def reservation_id_for(operation_id: str) -> str:
    return "reservation:company-db:" + raw_digest(operation_id).hex()
