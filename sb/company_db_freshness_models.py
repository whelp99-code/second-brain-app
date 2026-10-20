"""Typed registry, original evidence and durable operation rows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field

from sb.company_approver_binding import CompanyHandoffPolicy, Digest
from sb.company_freshness_models import (
    FreshnessScope,
    ProgressOperation,
    ProgressTerminalState,
)
from sb.company_memory_authority import CompanyAuthorityContext
from sb.company_memory_handoff import CompanyControlRequest
from sb.effect_values import JsonObject
from sb.effect_write_models import ClosedModel

type ActorStore = Literal["jarvis", "second_brain"]


class RegistryTpmPin(ClosedModel):
    identity: str = Field(min_length=1, max_length=256)
    public_name_hex: str = Field(pattern=r"^[0-9a-f]{2,512}$")
    nv_handle: Literal["0x01804F43"]
    name_alg: Literal["sha256"]
    initial_value_hex: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegistryScopePin(ClosedModel):
    provider_instance_id: str
    workspace_id: str
    epoch: int = Field(ge=1, le=9_007_199_254_740_991)
    genesis_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_deletion_sequence: int | None = Field(default=None, ge=0)
    source_deletion_root: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_context_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class RegistryAutoPolicyPin(ClosedModel):
    scope: FreshnessScope
    revision: int = Field(ge=1, le=9_007_199_254_740_991)
    policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    key_id: str = Field(pattern=r"^policy-auto:.+$")
    public_key_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    public_key: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    revoked_policy_digests: list[Digest]
    revoked_key_fingerprints: list[Digest]


class RegistryDeletionSource(ClosedModel):
    scope: FreshnessScope
    authority_id: str
    deletion_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    intent_path: str
    intent_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    completion_path: str | None
    completion_digest: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RegistryApprovalRevocation(ClosedModel):
    scope: FreshnessScope
    source_record_id: str = Field(min_length=1, max_length=512)
    original_at: str
    approval_policy_version: int = Field(ge=1, le=9_007_199_254_740_991)
    approval_binding_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: Literal["key_revoked", "policy_revoked"]
    revoked_key_fingerprints: list[Digest]


class FreshnessRegistry(ClosedModel):
    schema_version: Literal[1]
    registry_id: str
    installation_id: str
    tpm: RegistryTpmPin
    scopes: list[RegistryScopePin]
    auto_policies: list[RegistryAutoPolicyPin] = Field(default_factory=list)
    deletion_sources: list[RegistryDeletionSource] = Field(default_factory=list)
    approval_revocations: list[RegistryApprovalRevocation] = Field(default_factory=list)


class GenesisEntry(ClosedModel):
    source_record_id: str = Field(min_length=1, max_length=512)
    source_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_at: str = Field(min_length=24, max_length=24)
    metadata: JsonObject = Field(default_factory=dict)


class GenesisInventory(ClosedModel):
    jarvis_receipts: list[GenesisEntry] = Field(default_factory=list)
    jarvis_terminals: list[GenesisEntry] = Field(default_factory=list)
    jarvis_deletions: list[GenesisEntry] = Field(default_factory=list)
    second_brain_receipts: list[GenesisEntry] = Field(default_factory=list)
    second_brain_terminals: list[GenesisEntry] = Field(default_factory=list)
    second_brain_deletions: list[GenesisEntry] = Field(default_factory=list)
    revocations: list[GenesisEntry] = Field(default_factory=list)


class JarvisSidecarEvidence(ClosedModel):
    """Original record, not a new signature pretending to be human approval."""

    schema_version: Literal[1]
    kind: Literal["representative_receipt", "completion", "cancellation"]
    source_record_id: str = Field(min_length=1, max_length=512)
    original_at: str = Field(min_length=24, max_length=24)
    command: CompanyControlRequest
    record: JsonObject


class JarvisRecoveryEvidence(ClosedModel):
    sidecar: JarvisSidecarEvidence
    context: CompanyAuthorityContext
    policy: CompanyHandoffPolicy


class JarvisCompletionV2(ClosedModel):
    schema_version: Literal[2]
    state: Literal["completed"]
    request_id: str
    command_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_id: str
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    acceptance_receipt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    effect_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class JarvisCommandRevocationV1(ClosedModel):
    """The original immutable control_command_revocations row, not an approval."""

    revocation_id: str = Field(min_length=1, max_length=512)
    request_id: str = Field(min_length=1, max_length=512)
    receipt_id: str | None = Field(min_length=1, max_length=512)
    command_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4096)
    revoked_by: str = Field(min_length=1, max_length=512)
    revoked_at: str = Field(min_length=1, max_length=128)
    payload_json: str
    payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: str = Field(min_length=24, max_length=24)


class JarvisCancellationV1(ClosedModel):
    """Authenticated peer projection of an unclaimed, cancelled original request."""

    schema_version: Literal[1]
    state: Literal["cancelled"]
    lease_fence: int = Field(strict=True, ge=0, le=0)
    effect_record_id: None
    revocation: JarvisCommandRevocationV1


@dataclass(frozen=True, slots=True)
class VerifiedEvidence:
    source_record_id: str
    source_digest: str
    original_at: str
    metadata: JsonObject


class EvidenceVerifier(Protocol):
    def verify(
        self,
        connection: sqlite3.Connection,
        *,
        scope: FreshnessScope,
        actor_store: ActorStore,
        operation: ProgressOperation,
        operation_id: str,
        event_digest: str,
        evidence_digest: str,
        terminal_state: ProgressTerminalState,
    ) -> VerifiedEvidence: ...


class EvidenceRejected(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code: str = code


class OperationRow(ClosedModel):
    operation_id: str
    operation: ProgressOperation
    actor_store: ActorStore
    event_digest: str
    reservation_id: str
    reserve_expected_json: str
    reserved_checkpoint_json: str
    state: Literal["reserved", "finished"]
    finish_expected_json: str | None
    evidence_digest: str | None
    terminal_state: ProgressTerminalState | None
    finished_checkpoint_json: str | None


class WitnessTransport(ClosedModel):
    challenge: str
    reservation_id: str | None
    terminal_state: ProgressTerminalState | None
