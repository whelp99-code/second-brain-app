"""Read operator-registered original deletion facts; never delete candidate rows."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field

from sb.company_db_freshness_hash import deletion_operation_id
from sb.company_db_freshness_models import (
    EvidenceRejected,
    FreshnessRegistry,
    RegistryDeletionSource,
    VerifiedEvidence,
)
from sb.company_freshness_anchor import require_trusted_file
from sb.company_freshness_models import FreshnessScope
from sb.effect_values import canonical_bytes, format_instant, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class DeletionFact(ClosedModel):
    """Body-free projection exported by the existing approved deletion authority."""

    schema_version: Literal[1]
    scope: FreshnessScope
    authority_id: str
    source_record_id: str
    deletion_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    authorization_receipt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_fence: int = Field(ge=0, le=9_007_199_254_740_991)
    source_root: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_at: str
    stage: Literal["intent", "deleted"]


def deletion_source(
    registry: FreshnessRegistry,
    scope: FreshnessScope,
    operation_id: str,
) -> RegistryDeletionSource:
    found = [
        source
        for source in registry.deletion_sources
        if source.scope == scope
        and deletion_operation_id(scope, source.deletion_plan_digest) == operation_id
    ]
    if len(found) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    return found[0]


def original_deletion_fact(
    source: RegistryDeletionSource,
    stage: Literal["intent", "deleted"],
) -> tuple[DeletionFact, str]:
    path_value = source.intent_path if stage == "intent" else source.completion_path
    expected = source.intent_digest if stage == "intent" else source.completion_digest
    if path_value is None or expected is None:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    path = Path(path_value)
    require_trusted_file(path, mode=0o600)
    if path.stat().st_size > 65_536:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    fact = DeletionFact.model_validate_json(path.read_bytes(), strict=True)
    digest = "sha256:" + hashlib.sha256(canonical_bytes(model_object(fact))).hexdigest()
    if (
        digest != expected
        or fact.scope != source.scope
        or fact.authority_id != source.authority_id
        or fact.deletion_plan_digest != source.deletion_plan_digest
        or fact.stage != stage
        or format_instant(parse_instant(fact.original_at)) != fact.original_at
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    return fact, digest


def verify_original_deletion(
    registry: FreshnessRegistry,
    scope: FreshnessScope,
    operation_id: str,
    event_digest: str,
    evidence_digest: str,
) -> VerifiedEvidence:
    source = deletion_source(registry, scope, operation_id)
    intent, digest = original_deletion_fact(source, "intent")
    completed, completed_digest = original_deletion_fact(source, "deleted")
    if (
        event_digest != digest
        or evidence_digest != completed_digest
        or intent.source_fence != completed.source_fence
        or intent.source_root != completed.source_root
        or intent.authorization_receipt_digest != completed.authorization_receipt_digest
        or parse_instant(completed.original_at) < parse_instant(intent.original_at)
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    return deletion_evidence(completed, completed_digest)


def deletion_evidence(fact: DeletionFact, digest: str) -> VerifiedEvidence:
    return VerifiedEvidence(
        fact.source_record_id,
        digest,
        fact.original_at,
        {
            "deletion_plan_digest": fact.deletion_plan_digest,
            "source_fence": fact.source_fence,
            "source_root": fact.source_root,
            "authorization_receipt_digest": fact.authorization_receipt_digest,
            "authority_id": fact.authority_id,
        },
    )
