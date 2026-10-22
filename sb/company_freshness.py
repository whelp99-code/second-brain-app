"""Public freshness factory and guards; wire types remain re-exported."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from sb.company_db_freshness import company_db_provider_from_factory
from sb.company_freshness_models import (
    MAX_SAFE_INTEGER,
    TERMINAL_STATE_BY_OPERATION,
    Checkpoint,
    CompanyFreshnessProvider,
    FinishOutcome,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessErrorCode,
    FreshnessProviderConfig,
    FreshnessScope,
    FreshnessStatus,
    FreshnessWireError,
    ProgressOperation,
    ProgressTerminalState,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveOutcome,
    ReserveProgressRequest,
    ReserveProgressResponse,
    StoreHeads,
    StoreProgress,
)
from sb.company_freshness_progress import is_other_store_prefix as _other_store_prefix
from sb.company_memory_authority import CompanyAuthorityRejected

__all__ = [
    "MAX_SAFE_INTEGER",
    "TERMINAL_STATE_BY_OPERATION",
    "Checkpoint",
    "CompanyFreshnessProvider",
    "FinishOutcome",
    "FinishProgressRequest",
    "FinishProgressResponse",
    "FreshnessErrorCode",
    "FreshnessProviderConfig",
    "FreshnessScope",
    "FreshnessStatus",
    "FreshnessWireError",
    "ProgressOperation",
    "ProgressTerminalState",
    "ReadFreshnessRequest",
    "ReadFreshnessResponse",
    "ReserveOutcome",
    "ReserveProgressRequest",
    "ReserveProgressResponse",
    "StoreHeads",
    "StoreProgress",
    "UnconfiguredCompanyFreshnessProvider",
    "provider_from_config",
    "require_company_db_freshness",
    "require_freshness",
]


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
    *,
    company_database: Path | None = None,
    actor_store: Literal["jarvis", "second_brain"] = "second_brain",
) -> CompanyFreshnessProvider:
    """Build a provider. The database is an explicit argument, never a config path.

    `sb_company_db` uses the fixed registry, witness, and lock paths. Tests inject
    those only through `CompanyDbFreshnessProvider`, not through this factory.
    """
    match config.kind:
        case "unconfigured":
            del company_database, actor_store
            return UnconfiguredCompanyFreshnessProvider()
        case "sb_company_db":
            return company_db_provider_from_factory(
                config,
                company_database=company_database,
                actor_store=actor_store,
            )


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


def require_company_db_freshness(
    provider: CompanyFreshnessProvider,
    request: ReadFreshnessRequest,
    *,
    actor_store: Literal["jarvis", "second_brain"],
) -> Checkpoint:
    """Ready-head acceptance for `sb_company_db` only.

    Exact echo still succeeds. A ready head also succeeds when epoch, policy,
    binding, revocation, and the caller store are unchanged and the other store
    is a forward prefix. `require_freshness` stays strict so unconfigured and
    TEST_ONLY equality do not change. Callers of those providers must not use
    this helper to accept a diverged head.
    """
    try:
        response = provider.read_freshness(request)
    except TimeoutError as exc:
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    except OSError as exc:
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    if (
        response.status == "ready"
        and response.checkpoint is not None
        and request.observed_checkpoint is not None
        and response.scope == request.scope
        and response.challenge == request.challenge
        and _other_store_prefix(request.observed_checkpoint, response.checkpoint, actor_store)
    ):
        return response.checkpoint
    return _accepted_checkpoint(request, response)


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
