from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest

from sb.company_freshness import (
    Checkpoint,
    FinishOutcome,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessProviderConfig,
    FreshnessWireError,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.company_processor_finish import PendingFinish
from sb.effect_values import JsonObject, canonical_bytes
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
from tests.test_company_memory_product import NOW, RECEIVE
from tests.test_company_memory_profile import decoded_object


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
        self.finish_outcomes: list[FinishOutcome] = []
        self.factory_configs: list[FreshnessProviderConfig] = []
        self.before: list[tuple[str, int]] = states(config)
        self.after: str = "accepted"
        self.after_states: list[tuple[str, int]] | None = None

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
        assert states(self.config) == (
            self.after_states if self.after_states is not None else [(self.after, 1)]
        )
        with closing(sqlite3.connect(self.config.parent / "company" / "company.db")) as db:
            assert (
                db.execute(
                    "SELECT 1 FROM company_memory_receipts WHERE receipt_digest=?",
                    (request.evidence_digest,),
                ).fetchone()
                is not None
            )
            rows: list[tuple[str]] = db.execute(
                "SELECT pending_json FROM company_processor_pending_finish WHERE workspace_id=?",
                (request.scope.workspace_id,),
            ).fetchall()
            assert len(rows) == 1
            pending = PendingFinish.model_validate_json(rows[0][0])
            assert pending.operation_id == request.operation_id
            assert pending.reservation.reservation_id == request.reservation_id
            assert pending.reservation.checkpoint == request.expected_checkpoint
        if not any(r.reservation_id == request.reservation_id for r in self.finishes):
            self.events.append("committed_effect")
        self.events.append("finish")
        self.finishes.append(request)
        if self.finish_mode == "lost_before":
            raise TimeoutError("TEST_ONLY finish response unavailable")
        result = self.inner.finish_progress(request)
        self.finish_outcomes.append(result.outcome)
        if self.finish_mode == "lost_after":
            raise TimeoutError("TEST_ONLY recorded finish acknowledgment lost")
        return result


def invoke(
    config: Path,
    provider: ObservedProvider,
    operation: Literal["accept", "reject", "mark_processed"],
    arguments: JsonObject,
) -> None:
    def select_provider(
        configured: FreshnessProviderConfig,
        *,
        company_database: object = None,
    ) -> ObservedProvider:
        del company_database
        assert configured == FreshnessProviderConfig(schema_version=2, kind="unconfigured")
        provider.factory_configs.append(configured)
        return provider

    # Model the configuration factory's backend, not the run() injection argument.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("sb.company_memory_cli.provider_from_config", select_provider)
        _ = run(
            config,
            signed_request(operation, arguments, PROCESSOR_KEY, "processor", PROCESSOR),
            now=NOW,
            process_only=True,
            # The newest outside head must not bypass a restored durable checkpoint.
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
        provider.finish_outcomes.clear()
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


def process_another_candidate(config: Path, provider: ObservedProvider) -> None:
    other: JsonObject = {**RECEIVE, "candidate_id": "candidate-after-finish-retry"}
    _ = run(config.parent / "legacy.json", signed_request("receive", other), now=NOW)
    proposal = first_proposal(handoff(config))
    provider.before = states(config)
    expected = dict(provider.before)
    expected["candidate"] -= 1
    if not expected["candidate"]:
        del expected["candidate"]
    expected["accepted"] = expected.get("accepted", 0) + 1
    provider.after_states = sorted(expected.items())
    arguments = processor_arguments(
        proposal,
        owner_receipt(proposal, changes={"receipt_id": "owner-receipt:after-retry"}),
    )
    invoke(config, provider, "accept", arguments)
    assert states(config) == provider.after_states


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
def test_configuration_selected_finish_retry_preserves_effect_and_restore_guard(
    prepared: tuple[Path, JsonObject],
    finish: Literal["lost_before", "lost_after"],
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    provider.finish_mode = finish
    restored_states = provider.before.copy()
    database = config.parent / "company" / "company.db"
    backup, config_before = database.read_bytes(), config.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        invoke(config, provider, operation, arguments)
    assert states(config) == [(provider.after, 1)]
    with closing(sqlite3.connect(database)) as db:
        original_receipts: list[tuple[str, ...]] = db.execute(
            "SELECT * FROM company_memory_receipts",
        ).fetchall()
    provider.finish_mode = "normal"
    invoke(config, provider, operation, arguments)
    assert len(provider.reservations) == 1
    assert len(provider.finishes) == 2
    assert provider.finishes[0].reservation_id == provider.finishes[1].reservation_id
    assert provider.finishes[0].expected_checkpoint == provider.finishes[1].expected_checkpoint
    assert provider.finishes[0].evidence_digest == provider.finishes[1].evidence_digest
    assert provider.finish_outcomes[-1] == (
        "recorded" if finish == "lost_before" else "already_recorded"
    )
    assert provider.events == ["reserve", "committed_effect", "finish", "finish"]
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT * FROM company_memory_receipts").fetchall() == original_receipts
        assert db.execute("SELECT count(*) FROM company_processor_pending_finish").fetchone() == (
            0,
        )
    process_another_candidate(config, provider)
    assert len(provider.reservations) == 2
    assert len(provider.finishes) == 3
    # Restore only the SB DB while the SAME outside-restore provider object survives.
    _ = database.write_bytes(backup)
    before = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected):
        invoke(config, provider, operation, arguments)
    assert config.read_bytes() == config_before
    assert database.read_bytes() == before
    assert states(config) == restored_states
    assert len(provider.reservations) == 2
    assert len(provider.finishes) == 3


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


@pytest.mark.parametrize("finish", ["lost_before", "lost_after"])
@pytest.mark.parametrize(
    "damage",
    ["signature", "missing_receipt", "corrupt_receipt", "missing_reservation"],
)
def test_finish_recovery_requires_authority_and_committed_local_evidence(
    prepared: tuple[Path, JsonObject],
    finish: Literal["lost_before", "lost_after"],
    damage: str,
) -> None:
    config, proposal = prepared
    provider = ObservedProvider(config, finish=finish)
    arguments = processor_arguments(proposal, owner_receipt(proposal))
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        invoke(config, provider, "accept", arguments)
    provider.finish_mode = "normal"
    raw = signed_request("accept", arguments, PROCESSOR_KEY, "processor", PROCESSOR)
    if damage == "signature":
        envelope = decoded_object(raw)
        authority = envelope["authority"]
        assert isinstance(authority, dict)
        authority["signature"] = "A" * 86
        raw = canonical_bytes(envelope)
    else:
        statements = {
            "missing_receipt": "DELETE FROM company_memory_receipts WHERE operation='accept'",
            "corrupt_receipt": "UPDATE company_memory_receipts SET receipt_digest='corrupt' WHERE operation='accept'",
            "missing_reservation": "DELETE FROM company_processor_pending_finish",
        }
        with closing(sqlite3.connect(config.parent / "company" / "company.db")) as db, db:
            _ = db.execute(statements[damage])
    database = config.parent / "company" / "company.db"
    before, events = database.read_bytes(), provider.events.copy()
    with pytest.raises(CompanyAuthorityRejected):
        _ = run(
            config,
            raw,
            now=NOW,
            process_only=True,
            freshness_provider=provider,
            observed_checkpoint=provider.inner.checkpoint,
        )
    assert database.read_bytes() == before
    assert provider.events == events


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
