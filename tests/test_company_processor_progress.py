from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest

from sb.company_freshness import (
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessWireError,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.effect_values import JsonObject
from tests.company_approver_test_freshness import TestOnlyMemoryFreshnessProvider
from tests.company_approver_test_runtime import provider_for_config
from tests.test_company_candidate_handoff import (
    PROCESSOR,
    PROCESSOR_KEY,
    enroll,
    first_proposal,
    handoff,
    owner_receipt,
    processor_arguments,
    setup_config,
    signed_request,
    states,
)
from tests.test_company_memory_product import NOW


class ObservedProvider:
    def __init__(
        self,
        config: Path,
        *,
        reserve: Literal["normal", "conflict", "error", "already_reserved"] = "normal",
        finish: Literal["normal", "lost_before", "lost_after"] = "normal",
    ) -> None:
        inner, checkpoint = provider_for_config(config)
        assert isinstance(inner, TestOnlyMemoryFreshnessProvider)
        self.inner: TestOnlyMemoryFreshnessProvider = inner
        self.initial: Checkpoint = checkpoint
        self.config: Path = config
        self.reserve_mode: Literal["normal", "conflict", "error", "already_reserved"] = reserve
        self.finish_mode: Literal["normal", "lost_before", "lost_after"] = finish
        self.events: list[str] = []
        self.reservations: list[ReserveProgressRequest] = []
        self.finishes: list[FinishProgressRequest] = []
        self.before: list[tuple[str, int]] = states(config)
        self.after: str = "accepted"

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        return self.inner.read_freshness(request)

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        # Read the committed database, not a fake call counter standing in for the effect.
        assert states(self.config) == self.before
        self.events.append("reserve")
        self.reservations.append(request)
        if self.reserve_mode == "error":
            return FreshnessWireError(
                schema_version=2,
                outcome="error",
                code="COMPANY_FRESHNESS_REQUIRED",
            )
        if self.reserve_mode == "conflict":
            return ReserveProgressResponse(
                schema_version=2,
                scope=request.scope,
                challenge=request.challenge,
                outcome="conflict",
                checkpoint=None,
                reservation_id=None,
            )
        result = self.inner.reserve_progress(request)
        if self.reserve_mode == "already_reserved":
            return result.model_copy(update={"outcome": "already_reserved"})
        return result

    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse:
        assert states(self.config) == [(self.after, 1)]
        with closing(sqlite3.connect(self.config.parent / "company" / "company.db")) as db:
            assert (
                db.execute(
                    "SELECT 1 FROM company_memory_receipts WHERE receipt_digest=?",
                    (request.evidence_digest,),
                ).fetchone()
                is not None
            )
        self.events.extend(("committed_effect", "finish"))
        self.finishes.append(request)
        if self.finish_mode == "lost_before":
            raise TimeoutError("TEST_ONLY finish response unavailable")
        result = self.inner.finish_progress(request)
        if self.finish_mode == "lost_after":
            raise TimeoutError("TEST_ONLY recorded finish acknowledgment lost")
        return result


def invoke(
    config: Path,
    provider: ObservedProvider,
    operation: Literal["accept", "reject", "mark_processed"],
    arguments: JsonObject,
) -> None:
    _ = run(
        config,
        signed_request(operation, arguments, PROCESSOR_KEY, "processor", PROCESSOR),
        now=NOW,
        process_only=True,
        freshness_provider=provider,
        # Deliberately pass the newest provider head. The product must still compare
        # its durable local checkpoint, not trust this as a restoration bypass.
        observed_checkpoint=provider.inner.checkpoint,
    )


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, JsonObject]:
    config = setup_config(tmp_path)
    _ = enroll(config)
    proposal = first_proposal(handoff(config))
    return config, proposal


def operation_arguments(
    config: Path,
    proposal: JsonObject,
    provider: ObservedProvider,
    operation: Literal["accept", "reject", "mark_processed"],
) -> JsonObject:
    if operation == "mark_processed":
        invoke(config, provider, "accept", processor_arguments(proposal, owner_receipt(proposal)))
        provider.before = states(config)
        provider.after = "processed_complete"
        provider.events.clear()
        provider.reservations.clear()
        provider.finishes.clear()
    else:
        provider.after = "rejected" if operation == "reject" else "accepted"
    return processor_arguments(
        proposal,
        None
        if operation == "mark_processed"
        else owner_receipt(
            proposal,
            "reject" if operation == "reject" else "approve",
        ),
    )


@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_processor_reserves_before_committed_effect_and_finishes(
    prepared: tuple[Path, JsonObject],
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    invoke(config, provider, operation, arguments)
    assert provider.events == ["reserve", "committed_effect", "finish"]
    assert provider.finishes[-1].terminal_state == provider.after
    assert provider.finishes[-1].operation_id == provider.reservations[-1].operation_id
    assert provider.inner.checkpoint.intent_sequence == (4 if operation == "mark_processed" else 2)


@pytest.mark.parametrize("mode", ["conflict", "error", "already_reserved"])
def test_processor_reserve_refusal_never_applies_effect(
    prepared: tuple[Path, JsonObject],
    mode: Literal["conflict", "error", "already_reserved"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config, reserve=mode)
    database = config.parent / "company" / "company.db"
    before = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected):
        invoke(config, provider, "accept", processor_arguments(proposal, owner_receipt(proposal)))
    assert provider.events == ["reserve"]
    assert states(config) == [("candidate", 1)]
    assert database.read_bytes() == before


@pytest.mark.parametrize("finish", ["lost_before", "lost_after"])
@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_finish_response_loss_blocks_reexecution_and_same_binding_restore(
    prepared: tuple[Path, JsonObject],
    finish: Literal["lost_before", "lost_after"],
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    provider.finish_mode = finish
    database = config.parent / "company" / "company.db"
    backup, config_before = database.read_bytes(), config.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        invoke(config, provider, operation, arguments)
    assert states(config) == [(provider.after, 1)]
    provider.finish_mode = "normal"
    with pytest.raises(CompanyAuthorityRejected):
        invoke(config, provider, operation, arguments)
    assert len(provider.reservations) == len(provider.finishes) == 1
    # Restore only the SB DB while the SAME outside-restore provider object survives.
    _ = database.write_bytes(backup)
    before = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected):
        invoke(config, provider, operation, arguments)
    assert config.read_bytes() == config_before
    assert database.read_bytes() == before
    assert states(config) == provider.before
    assert len(provider.reservations) == len(provider.finishes) == 1


@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_completed_effect_cannot_reexecute_after_same_binding_database_restore(
    prepared: tuple[Path, JsonObject],
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    database = config.parent / "company" / "company.db"
    backup, config_before = database.read_bytes(), config.read_bytes()
    invoke(config, provider, operation, arguments)
    assert len(provider.reservations) == len(provider.finishes) == 1
    _ = database.write_bytes(backup)
    before = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_OPERATIONAL_ROLLBACK"):
        invoke(config, provider, operation, arguments)
    assert database.read_bytes() == before
    assert config.read_bytes() == config_before
    assert len(provider.reservations) == len(provider.finishes) == 1


@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_verified_original_receipt_retry_does_not_reserve_another_effect(
    prepared: tuple[Path, JsonObject],
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    invoke(config, provider, operation, arguments)
    invoke(config, provider, operation, arguments)
    assert len(provider.reservations) == len(provider.finishes) == 1
    assert states(config) == [(provider.after, 1)]
