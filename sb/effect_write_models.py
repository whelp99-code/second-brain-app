"""Strict Pydantic models for the Task 30 V2 memory-effect wire contract."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DigestText = str
InstantText = str


class EffectModelError(ValueError):
    pass


class ClosedModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class ResolvedMemoryTargetModel(ClosedModel):
    schema_version: Literal[1]
    target_id: str
    target_digest: DigestText
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: DigestText
    vault_head: str
    vault_tree: str
    page_id: str
    page_blob_oid: str
    page_content_digest: DigestText
    source_identity_full: str
    content_identity_full: str
    citation_identity_full: str
    citation_span_start: int
    citation_span_end: int
    subject_digest: DigestText
    sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    valid_from: InstantText
    valid_until: InstantText
    source_owner_class: Literal["provider_owned", "external_read_only"]
    source_owner_id_digest: DigestText
    resolved_at: InstantText
    expires_at: InstantText


class TargetScopeModel(ClosedModel):
    format: Literal["none", "json"]
    sensitivity_classes: list[Literal["public", "personal", "sensitive", "restricted"]]
    valid_from: InstantText
    valid_until: InstantText
    max_records: int
    max_bytes: int
    source_owner_classes: list[Literal["provider_owned", "external_read_only"]]


class ExpectedPriorModelV2(ClosedModel):
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: DigestText
    vault_head: str
    vault_tree: str
    page_blob_oid: str
    page_content_digest: DigestText
    citation_identity_full: str


class TombstoneHighWaterModel(ClosedModel):
    sequence: int
    set_root: DigestText


class TombstoneChainEntryModel(ClosedModel):
    sequence: int
    tombstone_id: str
    operation: Literal["correct", "forget"]
    lane_id: str
    target_manifest_digest: DigestText
    scope_digest: DigestText
    authority_receipt_digest: DigestText
    payload_digest: DigestText
    keyed_subject_digest: str
    effective_at: InstantText
    previous_root: DigestText
    set_root: DigestText


class ExternalErasureReceiptModel(ClosedModel):
    owner_id_digest: DigestText
    receipt_id: str
    receipt_digest: DigestText
    scope_digest: DigestText
    deleted_at: InstantText
    signing_key_id: str
    signature: str


class CorrectionPayloadModelV2(ClosedModel):
    content: str
    content_digest: DigestText
    content_bytes: int
    disposition: Literal["superseded"]


class DeletePayloadModelV2(ClosedModel):
    disposition: Literal["owner_requested"]
    erasure_claim: Literal["managed_erasure", "provider_local_suppression"]
    external_receipts: list[ExternalErasureReceiptModel]


class ExportPayloadModelV2(ClosedModel):
    format: Literal["json"]
    target_record_ids: list[str]
    sensitivity_classes: list[Literal["public", "personal", "sensitive", "restricted"]]
    valid_from: InstantText
    valid_until: InstantText
    max_records: int
    max_bytes: int


type MemoryEffectPayloadModel = (
    CorrectionPayloadModelV2 | DeletePayloadModelV2 | ExportPayloadModelV2
)


class MemoryEffectDelegationModel(ClosedModel):
    schema_version: Literal[1]
    delegation_id: str
    delegation_digest: DigestText
    provider_instance_id: str
    purpose: Literal["memory_correction", "memory_delete", "memory_export"]
    operation: Literal["correct", "forget", "export"]
    lane_id: str
    request_id: str
    request_digest: DigestText
    payload_digest: DigestText
    target_manifest_digest: DigestText
    scope_digest: DigestText
    expected_prior: ExpectedPriorModelV2
    tombstone_sequence: int
    tombstone_set_root: DigestText
    principal_id: Literal["principal:owner"]
    issued_at: InstantText
    not_before: InstantText
    expires_at: InstantText
    nonce: str
    max_uses: Literal[1]
    signing_key_id: str
    signature: str


class MemoryEffectWriteRequestV2(ClosedModel):
    schema_version: Literal[2]
    kind: Literal["memory_effect"]
    provider_instance_id: str
    lane: Literal["correction", "deletion", "export"]
    lane_id: str
    operation: Literal["correct", "forget", "export"]
    request_id: str
    request_digest: DigestText
    idempotency_key: str
    envelope_digest: DigestText
    target_manifest_digest: DigestText
    targets: list[ResolvedMemoryTargetModel] = Field(min_length=1, max_length=64)
    scope: TargetScopeModel
    scope_digest: DigestText
    expected_prior: ExpectedPriorModelV2
    tombstone_high_water: TombstoneHighWaterModel
    tombstone_chain_delta: list[TombstoneChainEntryModel] = Field(max_length=256)
    delegation: MemoryEffectDelegationModel
    created_at: InstantText
    expires_at: InstantText
    payload: MemoryEffectPayloadModel

    @model_validator(mode="after")
    def operation_union(self) -> MemoryEffectWriteRequestV2:
        valid = self.lane == "correction" and self.operation == "correct"
        valid = valid and isinstance(self.payload, CorrectionPayloadModelV2)
        if valid:
            return self
        valid = self.lane == "deletion" and self.operation == "forget"
        valid = valid and isinstance(self.payload, DeletePayloadModelV2)
        if valid:
            return self
        valid = self.lane == "export" and self.operation == "export"
        valid = valid and isinstance(self.payload, ExportPayloadModelV2)
        if not valid:
            raise EffectModelError("EFFECT_OPERATION_CONFUSION")
        return self


class MemoryEffectWriteAcceptedV2(ClosedModel):
    schema_version: Literal[2]
    kind: Literal["accepted"]
    state: Literal["pending"]
    request_id: str
    request_digest: DigestText
    idempotency_key: str
    envelope_digest: DigestText
    lane: Literal["correction", "deletion", "export"]
    operation: Literal["correct", "forget", "export"]
    accepted_at: InstantText
    queue_locator: str
    request_file_digest: DigestText
    replayed: bool
    capability_verified: Literal[True]
    tombstone_sequence: int
    tombstone_set_root: DigestText
    provider_instance_id: str


class MemoryEffectWriteErrorV2(ClosedModel):
    schema_version: Literal[2]
    kind: Literal["error"]
    code: str
    retryable: Literal[False]
    request_id: str | None
