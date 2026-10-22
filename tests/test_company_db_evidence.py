"""A valid receipt for another operation is not the reserved operation's proof."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness import FinishProgressRequest, ReserveProgressRequest
from tests.test_company_db_freshness import (
    PROVIDER_SCOPE,
    RECEIPT_BINDING,
    freshness_read,
    insert_receipt,
    provider_at,
)


def test_receipt_from_another_request_cannot_finish_reservation(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE,
        request_id="unrelated:request",
        command_digest=RECEIPT_BINDING,
        operation="accept",
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest="sha256:" + "ff" * 32,
            challenge="reserve:unrelated",
        )
    )
    assert reserved.outcome == "reserved"
    assert reserved.checkpoint is not None and reserved.reservation_id is not None
    receipt = insert_receipt(provider.database)
    result = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=receipt,
            terminal_state="accepted",
            challenge="finish:unrelated",
        )
    )
    # The orphan SQL receipt now invalidates the snapshot before finish verification.
    assert result.outcome == "error"


def test_lost_own_receipt_cannot_be_hidden_by_matching_checkpoint(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE,
        request_id="own:receipt",
        command_digest=RECEIPT_BINDING,
        operation="accept",
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest=RECEIPT_BINDING,
            challenge="reserve:own",
        )
    )
    assert reserved.outcome == "reserved"
    assert reserved.checkpoint is not None and reserved.reservation_id is not None
    receipt = insert_receipt(provider.database)
    finished = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=receipt,
            terminal_state="accepted",
            challenge="finish:own",
        )
    )
    assert finished.outcome == "recorded"
    with closing(sqlite3.connect(provider.database)) as db, db:
        _ = db.execute("DELETE FROM company_memory_receipts")
    response = provider.read_freshness(
        freshness_read(provider).model_copy(update={"observed_checkpoint": finished.checkpoint}),
    )
    assert response.status != "ready"
    assert response.checkpoint is None


def test_unknown_zero_height_prefix_cannot_rebase(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    request = freshness_read(provider)
    assert request.observed_checkpoint is not None
    forged = request.observed_checkpoint.model_copy(
        update={
            "intent_root": "sha256:" + "99" * 32,
        }
    )
    response = provider.read_freshness(
        request.model_copy(update={"observed_checkpoint": forged}),
    )
    assert response.status == "mismatch"
    assert response.checkpoint is None
