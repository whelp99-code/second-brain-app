from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_db_freshness_hash import operation_id_for, reservation_id_for
from sb.company_freshness import (
    Checkpoint,
    FinishProgressRequest,
    FreshnessScope,
    ReadFreshnessRequest,
    ReserveProgressRequest,
)
from sb.company_freshness_anchor import AnchorRejected, append_witness_frame
from sb.effect_values import JsonObject
from tests.company_db_freshness_support import (
    SIMULATED_ANCHOR_LABEL,
    SimulatedNvAnchor,
    provider_for,
)

PROVIDER_SCOPE = FreshnessScope(provider_instance_id="provider.one", workspace_id="workspace.one")
RECEIPT_BINDING = "sha256:" + "ab" * 32
_NOW = "2026-10-16T00:00:01.000Z"


def _anchor() -> SimulatedNvAnchor:
    return SimulatedNvAnchor(name=b"\x22" * 32, value=b"\x11" * 32)


def provider_at(tmp_path: Path) -> CompanyDbFreshnessProvider:
    return provider_for(tmp_path, scope=PROVIDER_SCOPE, binding=RECEIPT_BINDING, anchor=_anchor())


def freshness_read(
    provider: CompanyDbFreshnessProvider, challenge: str = "challenge-1"
) -> ReadFreshnessRequest:
    with closing(sqlite3.connect(provider.database)) as db:
        rows: list[tuple[str]] = db.execute(
            """SELECT checkpoint_json FROM company_freshness_scopes
            WHERE provider_instance_id=? AND workspace_id=?""",
            (PROVIDER_SCOPE.provider_instance_id, PROVIDER_SCOPE.workspace_id),
        ).fetchall()
    assert len(rows) == 1
    head = Checkpoint.model_validate_json(rows[0][0], strict=True)
    return ReadFreshnessRequest(
        schema_version=2,
        scope=PROVIDER_SCOPE,
        installation_id="install-1",
        challenge=challenge,
        observed_checkpoint=head,
    )


def test_bootstrap_ignores_caller_checkpoint_and_missing_head_fails_closed(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    response = provider.read_freshness(freshness_read(provider))
    assert response.status == "ready"
    assert response.checkpoint is not None
    assert response.checkpoint.intent_sequence == 0
    connection = sqlite3.connect(provider.database)
    _ = connection.execute("DELETE FROM company_freshness_scopes")
    connection.commit()
    connection.close()
    missing = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            installation_id="install-1",
            challenge="missing",
            observed_checkpoint=response.checkpoint,
        ),
    )
    assert missing.status == "unavailable"
    assert missing.checkpoint is None


def test_same_reserve_is_idempotent_and_other_bytes_conflict(tmp_path: Path) -> None:
    anchor = _anchor()
    provider = provider_for(tmp_path, scope=PROVIDER_SCOPE, binding=RECEIPT_BINDING, anchor=anchor)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE,
        request_id="req-1",
        command_digest=RECEIPT_BINDING,
        operation="accept",
    )
    request = ReserveProgressRequest(
        schema_version=2,
        scope=PROVIDER_SCOPE,
        operation_id=operation_id,
        operation="accept",
        expected_checkpoint=head,
        event_digest=RECEIPT_BINDING,
        challenge="reserve-1",
    )
    first = provider.reserve_progress(request)
    assert first.outcome == "reserved"
    assert first.reservation_id == reservation_id_for(operation_id)
    assert anchor.extend_count == 2
    again = provider.reserve_progress(request.model_copy(update={"challenge": "reserve-2"}))
    assert again.outcome == "already_reserved"
    assert again.checkpoint == first.checkpoint
    assert anchor.extend_count == 2
    other = provider.reserve_progress(
        request.model_copy(update={"event_digest": "sha256:" + "cd" * 32, "challenge": "reserve-3"})
    )
    assert other.outcome == "conflict"
    assert other.checkpoint is None


def test_finish_verifies_original_receipt_and_rejects_tamper(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE, request_id="req-2", command_digest=RECEIPT_BINDING, operation="accept"
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest=RECEIPT_BINDING,
            challenge="reserve-a",
        ),
    )
    assert reserved.outcome == "reserved"
    assert reserved.checkpoint is not None
    assert reserved.reservation_id is not None
    digest = insert_receipt(provider.database)
    absent = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest="sha256:" + "11" * 32,
            terminal_state="accepted",
            challenge="finish-a",
        ),
    )
    assert absent.outcome == "error"
    assert absent.code == "COMPANY_RECEIPT_EVIDENCE_ABSENT"
    wrong_terminal = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=digest,
            terminal_state="rejected",
            challenge="finish-b",
        ),
    )
    assert wrong_terminal.outcome == "conflict"
    recorded = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=digest,
            terminal_state="accepted",
            challenge="finish-c",
        ),
    )
    assert recorded.outcome == "recorded"
    replay = provider.finish_progress(
        FinishProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=digest,
            terminal_state="accepted",
            challenge="finish-d",
        ),
    )
    assert replay.outcome == "already_recorded"
    assert replay.checkpoint == recorded.checkpoint


def test_witness_crash_resumes_without_second_extend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = _anchor()
    provider = provider_for(tmp_path, scope=PROVIDER_SCOPE, binding=RECEIPT_BINDING, anchor=anchor)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE, request_id="req-3", command_digest=RECEIPT_BINDING, operation="accept"
    )

    def fail_append(witness_dir: Path, body: dict[str, object]) -> None:
        del witness_dir, body
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

    monkeypatch.setattr("sb.company_db_freshness.append_witness_frame", fail_append)
    failed = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest=RECEIPT_BINDING,
            challenge="crash-1",
        ),
    )
    assert failed.outcome == "error"
    monkeypatch.setattr("sb.company_db_freshness.append_witness_frame", append_witness_frame)
    before = anchor.extend_count
    resumed = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest=RECEIPT_BINDING,
            challenge="crash-2",
        ),
    )
    assert resumed.outcome == "already_reserved"
    assert anchor.extend_count == before + 1


def test_other_store_prefix_is_ready_and_own_loss_is_mismatch(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    ready = provider.read_freshness(freshness_read(provider))
    assert ready.checkpoint is not None
    observed = ready.checkpoint.model_copy(
        update={
            "stores": ready.checkpoint.stores.model_copy(
                update={
                    "jarvis": ready.checkpoint.stores.jarvis.model_copy(
                        update={"receipt_sequence": 0}
                    ),
                },
            ),
        },
    )
    prefix = provider.read_freshness(
        freshness_read(provider).model_copy(
            update={"observed_checkpoint": observed, "challenge": "prefix"}
        )
    )
    assert prefix.status == "ready"
    assert prefix.checkpoint == ready.checkpoint
    own_loss = ready.checkpoint.model_copy(
        update={
            "stores": ready.checkpoint.stores.model_copy(
                update={
                    "second_brain": ready.checkpoint.stores.second_brain.model_copy(
                        update={"receipt_sequence": 4, "receipt_root": "sha256:" + "ef" * 32},
                    ),
                },
            ),
        },
    )
    mismatch = provider.read_freshness(
        freshness_read(provider).model_copy(
            update={"observed_checkpoint": own_loss, "challenge": "own"}
        )
    )
    assert mismatch.status == "mismatch"
    assert SIMULATED_ANCHOR_LABEL.startswith("simulated anchor")


def insert_receipt(database: Path) -> str:
    connection = sqlite3.connect(database)
    _ = connection.execute(
        """CREATE TABLE IF NOT EXISTS company_memory_receipts (
            workspace_id TEXT, request_digest TEXT, receipt_id TEXT, receipt_digest TEXT,
            operation TEXT, candidate_id TEXT, result_json TEXT, created_at TEXT
        )""",
    )
    result = "{}"
    from sb.company_db_freshness_hash import prefixed_digest

    body: JsonObject = {
        "schema_version": 1,
        "workspace_id": PROVIDER_SCOPE.workspace_id,
        "request_digest": RECEIPT_BINDING,
        "operation": "accept",
        "candidate_id": "cand-1",
        "result": {},
        "created_at": _NOW,
    }
    real = prefixed_digest(b"second-brain/company-memory-receipt/v1\0", body)
    _ = connection.execute(
        "INSERT INTO company_memory_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            PROVIDER_SCOPE.workspace_id,
            body["request_digest"],
            "cmreceipt:v1:" + real.removeprefix("sha256:"),
            real,
            "accept",
            "cand-1",
            result,
            _NOW,
        ),
    )
    # Model a real atomic apply: its original reservation and pending finish
    # accompany the SQL receipt. An unrelated receipt intentionally has neither.
    operation = connection.execute(
        """SELECT operation_id,reservation_id,reserved_checkpoint_json
        FROM company_freshness_operations WHERE workspace_id=? AND event_digest=?
        AND operation='accept' AND state='reserved'""",
        (PROVIDER_SCOPE.workspace_id, RECEIPT_BINDING),
    ).fetchone()
    if operation is not None:
        from sb.company_freshness_models import ReserveProgressResponse
        from sb.company_processor_finish import PendingFinish, save_pending_finish

        connection.execute(
            """CREATE TABLE IF NOT EXISTS company_processor_pending_finish (
            workspace_id TEXT, request_digest TEXT, pending_json TEXT,
            PRIMARY KEY(workspace_id,request_digest))"""
        )
        save_pending_finish(
            connection,
            PROVIDER_SCOPE.workspace_id,
            RECEIPT_BINDING,
            PendingFinish(
                operation="accept",
                operation_id=operation[0],
                reservation=ReserveProgressResponse(
                    schema_version=2,
                    scope=PROVIDER_SCOPE,
                    outcome="reserved",
                    checkpoint=Checkpoint.model_validate_json(operation[2], strict=True),
                    reservation_id=operation[1],
                    challenge="fixture:original-reserve",
                ),
            ),
        )
    connection.commit()
    connection.close()
    return real
