"""Metadata-only cancellation intent. This is not an executable write request."""

from typing import Literal

from pydantic import Field, StrictBool, StrictInt

from sb.effect_write_models import (
    ClosedModel,
    MemoryEffectDelegationModel,
    ResolvedMemoryTargetModel,
    TargetScopeModel,
    TombstoneChainEntryModel,
)


class UnsentCorrectionEvidence(ClosedModel):
    candidate_id: str = Field(pattern=r"^memcand:pos:v1:[0-9a-f]{64}$")
    suppression_event_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dispatch_fence: StrictInt = Field(ge=0, le=0)
    attempt_count: StrictInt = Field(ge=0, le=0)
    active_cursor: StrictBool


class CancellationTarget(ResolvedMemoryTargetModel):
    provider_instance_id: str = Field(min_length=1, max_length=128)
    generation_id: str = Field(min_length=1, max_length=160)
    page_id: str = Field(min_length=1, max_length=512)


class CancellationDelegation(MemoryEffectDelegationModel):
    nonce: str = Field(min_length=1, max_length=128)
    signing_key_id: str = Field(min_length=1, max_length=128)


class CorrectionCancellationIntentV1(ClosedModel):
    schema_version: Literal[1]
    kind: Literal["memory_correction_cancellation_intent"]
    provider_instance_id: str = Field(min_length=1, max_length=128)
    reason: Literal["candidate_suppressed_unsent"]
    disposition: Literal["provider_local_suppression"]
    original_envelope_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_idempotency_key: str = Field(pattern=r"^memeff:idem:v2:[0-9a-f]{64}$")
    original_delegation: CancellationDelegation
    target: CancellationTarget
    scope: TargetScopeModel
    tombstone: TombstoneChainEntryModel
    unsent_evidence: UnsentCorrectionEvidence
    issued_at: str
    not_before: str
    expires_at: str
    nonce: str = Field(min_length=1, max_length=160)
    signing_key_id: str = Field(min_length=1, max_length=160)
    intent_id: str = Field(pattern=r"^memcancel:intent:v1:[0-9a-f]{64}$")
    intent_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")
