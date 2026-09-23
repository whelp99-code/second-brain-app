from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.company_memory import CompanyMemoryError, CompanyMemoryReceipt, CompanyMemoryStore
from sb.company_memory_authority import CompanyOperation, company_request_digest
from sb.effect_values import JsonObject
from sb.source_access import SourceAccess

WORKSPACE = "12345678-1234-4234-8234-123456789abc"
OTHER_WORKSPACE = "22345678-1234-4234-8234-123456789abc"
DELETION = (2, "sha256:" + "a" * 64)
NOW = datetime(2026, 9, 22, tzinfo=UTC)
SCOPE = SourceAccess("principal:owner", ("project:company",), "policy:1")


def receive(
    store: CompanyMemoryStore,
    workspace: str = WORKSPACE,
    candidate: str = "mail:1",
):
    return store.receive(
        workspace_id=workspace,
        candidate_id=candidate,
        source_system="mail",
        source_locator="msg/1",
        source_event_id="event:1",
        content="회의 일정",
        parser_version="mail:1",
        locator={"kind": "message", "ordinal": 1},
        access=SCOPE,
        deletion=DELETION,
    )


def execute(
    store: CompanyMemoryStore,
    operation: CompanyOperation,
    arguments: JsonObject | None = None,
) -> CompanyMemoryReceipt:
    values: JsonObject = {"candidate_id": "mail:1"} if arguments is None else arguments
    return store.execute(
        workspace_id=WORKSPACE,
        request_digest=company_request_digest(operation, values),
        operation=operation,
        arguments=values,
        current=SCOPE,
        deletion=DELETION,
        now=NOW,
    )


def test_company_candidate_explicit_transitions_and_replay(tmp_path: Path) -> None:
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        arguments: JsonObject = {
            "candidate_id": "mail:1",
            "source_system": "mail",
            "source_locator": "msg/1",
            "source_event_id": "event:1",
            "content": "회의 일정",
            "parser_version": "mail:1",
            "locator": {"kind": "message", "ordinal": 1},
        }
        first = execute(store, "receive", arguments)
        assert first.result["state"] == "candidate"
        assert execute(store, "receive", arguments) == first
        with pytest.raises(CompanyMemoryError, match="NOT_ACCEPTED"):
            _ = execute(store, "mark_processed")
        accepted = execute(store, "accept")
        assert accepted.result["state"] == "accepted"
        assert execute(store, "accept") == accepted
        complete = execute(store, "mark_processed")
        assert complete.result["state"] == "processed_complete"
        assert execute(store, "mark_processed") == complete
        with pytest.raises(CompanyMemoryError, match="TRANSITION_DENIED"):
            _ = execute(store, "reject")
    finally:
        store.close()


def test_durable_receipt_replay_detects_tampering(tmp_path: Path) -> None:
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        arguments: JsonObject = {
            "candidate_id": "mail:1",
            "source_system": "mail",
            "source_locator": "msg/1",
            "source_event_id": "event:1",
            "content": "회의 일정",
            "parser_version": "mail:1",
            "locator": {"kind": "message", "ordinal": 1},
        }
        receipt = execute(store, "receive", arguments)
        _ = store.db.execute(
            "UPDATE company_memory_receipts SET result_json=? WHERE receipt_id=?",
            ('{"state":"forged"}', receipt.receipt_id),
        )
        store.db.commit()
        with pytest.raises(CompanyMemoryError, match="RECEIPT_CORRUPT"):
            _ = execute(store, "receive", arguments)
    finally:
        store.close()


def test_rejection_is_explicit_and_terminal(tmp_path: Path) -> None:
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        _ = receive(store)
        rejected = store.reject(WORKSPACE, "mail:1", SCOPE, DELETION, now=NOW)
        assert rejected.state == "rejected"
        assert store.reject(WORKSPACE, "mail:1", SCOPE, DELETION, now=NOW) == rejected
        with pytest.raises(CompanyMemoryError, match="TRANSITION_DENIED"):
            _ = store.accept(WORKSPACE, "mail:1", SCOPE, DELETION, now=NOW)
        with pytest.raises(CompanyMemoryError, match="NOT_ACCEPTED"):
            _ = store.mark_processed(WORKSPACE, "mail:1", SCOPE, DELETION, now=NOW)
    finally:
        store.close()


def test_workspace_scope_fence_and_immutable_conflict(tmp_path: Path) -> None:
    store = CompanyMemoryStore(tmp_path / "company.db")
    try:
        first = receive(store)
        second = receive(store, OTHER_WORKSPACE)
        assert first.workspace_id != second.workspace_id
        with pytest.raises(CompanyMemoryError, match="NOT_FOUND"):
            _ = store.get(
                "32345678-1234-4234-8234-123456789abc", "mail:1", SCOPE, DELETION
            )
        with pytest.raises(CompanyMemoryError, match="TOMBSTONE"):
            _ = store.get(WORKSPACE, "mail:1", SCOPE, (3, "sha256:" + "b" * 64))
        with pytest.raises(CompanyMemoryError, match="SCOPED"):
            _ = store.get(
                WORKSPACE,
                "mail:1",
                SourceAccess("principal:owner", ("project:other",), "policy:1"),
                DELETION,
            )
        with pytest.raises(CompanyMemoryError, match="CONFLICT"):
            _ = store.receive(
                workspace_id=WORKSPACE,
                candidate_id="mail:1",
                source_system="mail",
                source_locator="msg/changed",
                source_event_id="event:1",
                content="회의 일정",
                parser_version="mail:1",
                locator={"kind": "message", "ordinal": 1},
                access=SCOPE,
                deletion=DELETION,
            )
    finally:
        store.close()
