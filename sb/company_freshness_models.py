from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal, Protocol, Self

from pydantic import Field, model_serializer, model_validator

from sb.effect_values import JsonValue
from sb.effect_write_models import ClosedModel

MAX_SAFE_INTEGER: Final = 2**53 - 1
_DIGEST: Final = r"^sha256:[0-9a-f]{64}$"
_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

type FreshnessStatus = Literal["ready", "mismatch", "unavailable", "uncertain"]
type ReserveOutcome = Literal["reserved", "already_reserved", "conflict"]
type FinishOutcome = Literal["recorded", "already_recorded", "conflict"]
type ProgressOperation = Literal[
    "decide_approve",
    "decide_reject",
    "accept",
    "reject",
    "complete",
    "mark_processed",
    "delete",
]
type ProgressTerminalState = Literal[
    "approved",
    "rejected",
    "accepted",
    "completed",
    "processed_complete",
    "deleted",
    "cancelled",
]
TERMINAL_STATE_BY_OPERATION: Final[dict[ProgressOperation, ProgressTerminalState]] = {
    "decide_approve": "approved",
    "decide_reject": "rejected",
    "accept": "accepted",
    "reject": "rejected",
    "complete": "completed",
    "mark_processed": "processed_complete",
    "delete": "deleted",
}
type FreshnessErrorCode = Literal[
    "COMPANY_CONTRACT_INVALID",
    "COMPANY_APPROVAL_INVALID",
    "COMPANY_APPROVAL_REVOKED",
    "ENROLLMENT_REQUIRED",
    "COMPANY_FRESHNESS_REQUIRED",
    "COMPANY_OPERATIONAL_ROLLBACK",
    "COMPANY_PROGRESS_UNCERTAIN",
    "COMPANY_DUPLICATE_OPERATION",
    "COMPANY_RECEIPT_EVIDENCE_ABSENT",
    "COMPANY_VERIFIER_INVALID",
]


class FreshnessProviderConfig(ClosedModel):
    """Closed freshness config. `unconfigured` dump stays exactly two fields."""

    schema_version: Literal[2]
    kind: Literal["unconfigured", "sb_company_db"]
    registry_id: str | None = Field(default=None, pattern=_ID)

    @model_validator(mode="after")
    def registry_id_matches_kind(self) -> Self:
        match self.kind:
            case "unconfigured":
                if self.registry_id is not None:
                    raise ValueError("unconfigured rejects registry_id")
            case "sb_company_db":
                if self.registry_id is None:
                    raise ValueError("sb_company_db requires registry_id")
        return self

    @model_serializer(mode="wrap")
    def serialize_config(
        self,
        handler: Callable[[Self], dict[str, JsonValue]],
    ) -> dict[str, JsonValue]:
        dumped = handler(self)
        if dumped.get("registry_id") is None:
            _ = dumped.pop("registry_id", None)
        return dumped


class FreshnessScope(ClosedModel):
    provider_instance_id: str = Field(pattern=_ID)
    workspace_id: str = Field(pattern=_ID)


class StoreProgress(ClosedModel):
    receipt_sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    receipt_root: str = Field(pattern=_DIGEST)
    terminal_sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    terminal_root: str = Field(pattern=_DIGEST)
    deletion_sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    deletion_root: str = Field(pattern=_DIGEST)


class StoreHeads(ClosedModel):
    jarvis: StoreProgress
    second_brain: StoreProgress


class Checkpoint(ClosedModel):
    operational_epoch: int = Field(ge=1, le=MAX_SAFE_INTEGER)
    approval_policy_version: int = Field(ge=1, le=MAX_SAFE_INTEGER)
    approval_binding_digest: str = Field(pattern=_DIGEST)
    revocation_sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    revocation_root: str = Field(pattern=_DIGEST)
    stores: StoreHeads
    intent_sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    intent_root: str = Field(pattern=_DIGEST)


class ReadFreshnessRequest(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    installation_id: str = Field(pattern=_ID)
    challenge: str = Field(min_length=1, max_length=256)
    observed_checkpoint: Checkpoint | None


class ReadFreshnessResponse(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    challenge: str = Field(min_length=1, max_length=256)
    status: FreshnessStatus
    checkpoint: Checkpoint | None

    @model_validator(mode="after")
    def checkpoint_follows_status(self) -> Self:
        match self.status:
            case "ready":
                if self.checkpoint is None:
                    raise ValueError("ready requires a checkpoint")
            case "mismatch" | "unavailable" | "uncertain":
                if self.checkpoint is not None:
                    raise ValueError("non-ready checkpoint must be null")
        return self


class ReserveProgressRequest(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    operation_id: str = Field(pattern=_DIGEST)
    operation: ProgressOperation
    expected_checkpoint: Checkpoint
    event_digest: str = Field(pattern=_DIGEST)
    challenge: str = Field(min_length=1, max_length=256)


class ReserveProgressResponse(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    challenge: str = Field(min_length=1, max_length=256)
    outcome: ReserveOutcome
    checkpoint: Checkpoint | None
    reservation_id: str | None = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def reservation_follows_outcome(self) -> Self:
        match self.outcome:
            case "reserved" | "already_reserved":
                if self.checkpoint is None or self.reservation_id is None:
                    raise ValueError("reservation requires checkpoint and reservation_id")
            case "conflict":
                if self.checkpoint is not None or self.reservation_id is not None:
                    raise ValueError("conflict clears checkpoint and reservation_id")
        return self


class FinishProgressRequest(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    operation_id: str = Field(pattern=_DIGEST)
    reservation_id: str = Field(min_length=1, max_length=256)
    expected_checkpoint: Checkpoint
    evidence_digest: str = Field(pattern=_DIGEST)
    terminal_state: ProgressTerminalState
    challenge: str = Field(min_length=1, max_length=256)


class FinishProgressResponse(ClosedModel):
    schema_version: Literal[2]
    scope: FreshnessScope
    challenge: str = Field(min_length=1, max_length=256)
    outcome: FinishOutcome
    checkpoint: Checkpoint | None

    @model_validator(mode="after")
    def checkpoint_follows_outcome(self) -> Self:
        match self.outcome:
            case "recorded" | "already_recorded":
                if self.checkpoint is None:
                    raise ValueError("recorded finish requires a checkpoint")
            case "conflict":
                if self.checkpoint is not None:
                    raise ValueError("finish conflict clears checkpoint")
        return self


class FreshnessWireError(ClosedModel):
    schema_version: Literal[2]
    outcome: Literal["error"]
    code: FreshnessErrorCode


class CompanyFreshnessProvider(Protocol):
    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse: ...

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError: ...

    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError: ...
