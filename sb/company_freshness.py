from __future__ import annotations

from typing import Final, Literal, Protocol, Self

from pydantic import Field, model_validator

from sb.company_memory_authority import CompanyAuthorityRejected
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
    schema_version: Literal[2]
    kind: Literal["unconfigured"]


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


class UnconfiguredCompanyFreshnessProvider:
    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        return ReadFreshnessResponse(
            schema_version=2,
            scope=request.scope,
            challenge=request.challenge,
            status="unavailable",
            checkpoint=None,
        )

    def reserve_progress(self, request: ReserveProgressRequest) -> FreshnessWireError:
        del request
        return _unconfigured_error()

    def finish_progress(self, request: FinishProgressRequest) -> FreshnessWireError:
        del request
        return _unconfigured_error()


def provider_from_config(
    config: FreshnessProviderConfig,
) -> UnconfiguredCompanyFreshnessProvider:
    del config
    return UnconfiguredCompanyFreshnessProvider()


def require_freshness(
    provider: CompanyFreshnessProvider,
    request: ReadFreshnessRequest,
) -> Checkpoint:
    try:
        response = provider.read_freshness(request)
    except TimeoutError as exc:
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    except OSError as exc:
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    return _accepted_checkpoint(request, response)


def _unconfigured_error() -> FreshnessWireError:
    return FreshnessWireError(
        schema_version=2,
        outcome="error",
        code="COMPANY_FRESHNESS_REQUIRED",
    )


def _accepted_checkpoint(
    request: ReadFreshnessRequest,
    response: ReadFreshnessResponse,
) -> Checkpoint:
    match response.status:
        case "ready":
            checkpoint = response.checkpoint
            observed = request.observed_checkpoint
            if (
                checkpoint is None
                or observed is None
                or response.scope != request.scope
                or response.challenge != request.challenge
            ):
                raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED")
            if checkpoint != observed:
                raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
            return checkpoint
        case "mismatch":
            raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
        case "unavailable":
            raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED")
        case "uncertain":
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
