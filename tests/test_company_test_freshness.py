from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from threading import Barrier, Lock, Thread
from typing import cast

import pytest

from sb.company_freshness import (
    TERMINAL_STATE_BY_OPERATION,
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessScope,
    ProgressOperation,
    ProgressTerminalState,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
    require_freshness,
)
from sb.effect_values import JsonObject, canonical_bytes
from tests.company_approver_test_freshness import (
    TestOnlyContractError,
    TestOnlyMemoryFreshnessProvider,
    memory_from_factory,
    reservation_id_for,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "company-approver"
    / "company-approver-v2.test-only.json"
)
_EMPTY = "sha256:" + "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_fixture_case_array_matches_one_factory_canonically() -> None:
    fixture = _load()
    memory = _object(fixture["test_only_memory"])
    provider = memory_from_factory(_object(memory["factory_input"]))
    cases = memory["cases"]
    if not isinstance(cases, list) or not cases:
        raise AssertionError("test_only_memory cases must be a non-empty array")
    for case in cases:
        body = _object(case)
        response = _dispatch(provider, body["operation"], _object(body["request"]))
        expected = _object(body["response"])
        actual = _dump(response)
        assert canonical_bytes(actual) == canonical_bytes(expected)
        assert actual == expected
    assert provider.checkpoint.intent_sequence == 2


def test_top_level_read_freshness_is_not_this_provider() -> None:
    fixture = _load()
    memory = _object(fixture["test_only_memory"])
    provider = memory_from_factory(_object(memory["factory_input"]))
    request = ReadFreshnessRequest.model_validate(_object(fixture["read_freshness"])["request"])
    response = provider.read_freshness(request)
    unconfigured = _object(fixture["read_freshness"])["response"]
    assert response.status == "ready"
    assert canonical_bytes(_dump(response)) != canonical_bytes(unconfigured)


def test_require_freshness_accepts_matching_ready_echo() -> None:
    provider = _factory()
    request = ReadFreshnessRequest.model_validate(_case_request("ready"))
    checkpoint = require_freshness(provider, request)
    assert checkpoint == provider.checkpoint


def test_pending_reservation_never_reports_ready_even_with_current_checkpoint() -> None:
    # Given a durable intent whose effect/finish acknowledgment is still unresolved.
    provider = _factory()
    before = provider.checkpoint
    reserved = provider.reserve_progress(_reserve_at(before, _operation(1), "accept"))
    assert reserved.outcome == "reserved"
    head = provider.checkpoint
    # When a restarted reader supplies either the old or exact current checkpoint.
    for observed in (before, head):
        request = ReadFreshnessRequest.model_validate(_case_request("ready")).model_copy(
            update={"observed_checkpoint": observed},
        )
        response = provider.read_freshness(request)
        assert response.status == "uncertain"
        assert response.checkpoint is None
        assert provider.checkpoint == head
    # Then only recording the original finish can remove uncertainty; reads do not.
    finished = provider.finish_progress(_finish_at(head, _operation(1), "accepted", _digest(2)))
    assert finished.outcome == "recorded"
    request = ReadFreshnessRequest.model_validate(_case_request("ready")).model_copy(
        update={"observed_checkpoint": provider.checkpoint},
    )
    assert provider.read_freshness(request).status == "ready"


@pytest.mark.parametrize("operation", list(TERMINAL_STATE_BY_OPERATION))
def test_finish_records_only_the_reserved_operation_terminal_state(
    operation: ProgressOperation,
) -> None:
    # Given each operation reserved under the common closed terminal-state mapping.
    provider = _factory()
    reserved = provider.reserve_progress(_reserve_at(provider.checkpoint, _operation(1), operation))
    assert reserved.checkpoint is not None
    # When finishing with exactly the state's recorded operation mapping.
    response = provider.finish_progress(
        _finish_at(
            reserved.checkpoint, _operation(1), TERMINAL_STATE_BY_OPERATION[operation], _digest(2)
        ),
    )
    # Then the original intent becomes finished with one additional head append.
    assert response.outcome == "recorded"
    assert provider.checkpoint.intent_sequence == 2


def test_fixture_terminal_mapping_and_all_negative_cases() -> None:
    # Given the normative mapping and every shared wrong-state example.
    fixture = _load()
    assert TERMINAL_STATE_BY_OPERATION == fixture["terminal_state_by_operation"]
    cases = fixture["terminal_state_negative_cases"]
    assert isinstance(cases, list)
    for item in cases:
        case = _object(item)
        provider = _factory()
        reserve_body = _object(
            _reserve_at(provider.checkpoint, _operation(1), "accept").model_dump(mode="json"),
        )
        reserve_body["operation"] = case["operation"]
        request = ReserveProgressRequest.model_validate(reserve_body)
        reserved = provider.reserve_progress(request)
        assert reserved.checkpoint is not None
        head = provider.checkpoint
        finish_body = _object(
            _finish_at(
                head, _operation(1), TERMINAL_STATE_BY_OPERATION[request.operation], _digest(2)
            ).model_dump(mode="json"),
        )
        finish_body["terminal_state"] = case["terminal_state"]
        # When a caller supplies an unknown state or a different operation's state.
        if case["terminal_state"] not in TERMINAL_STATE_BY_OPERATION.values():
            with pytest.raises(ValueError):
                _ = FinishProgressRequest.model_validate(finish_body)
        else:
            response = provider.finish_progress(FinishProgressRequest.model_validate(finish_body))
            assert response.outcome == "conflict"
            assert response.checkpoint is None
        # Then unknown/conflicting state cannot erase uncertainty or rewrite the head.
        assert case["expected_valid"] is False
        assert provider.checkpoint == head
        read = ReadFreshnessRequest.model_validate(_case_request("ready")).model_copy(
            update={"observed_checkpoint": head},
        )
        assert provider.read_freshness(read).status == "uncertain"


def test_replay_uses_original_expected_and_does_not_move_head() -> None:
    provider = _factory()
    reserved = provider.reserve_progress(_reserve_at(provider.checkpoint, _operation(1), "accept"))
    assert reserved.outcome == "reserved"
    assert reserved.checkpoint is not None
    moved = reserved.checkpoint
    again = provider.reserve_progress(_reserve_at(provider.checkpoint, _operation(1), "accept"))
    assert again.outcome == "conflict"
    replay = provider.reserve_progress(
        _reserve_at(
            moved.model_copy(
                update={
                    "intent_sequence": 0,
                    "intent_root": _EMPTY,
                }
            ),
            _operation(1),
            "accept",
        )
    )
    assert replay.outcome == "already_reserved"
    assert replay.checkpoint == moved
    assert provider.checkpoint == moved

    foreign = provider.reserve_progress(
        _reserve_at(moved, _operation(1), "accept").model_copy(update={"event_digest": _digest(9)}),
    )
    assert foreign.outcome == "conflict"
    assert provider.checkpoint == moved


def test_finish_replay_requires_original_expected() -> None:
    provider = _factory()
    reserved = provider.reserve_progress(_reserve_at(provider.checkpoint, _operation(1), "accept"))
    assert reserved.checkpoint is not None
    recorded = provider.finish_progress(
        _finish_at(reserved.checkpoint, _operation(1), "accepted", _digest(2)),
    )
    assert recorded.outcome == "recorded"
    assert recorded.checkpoint is not None
    head = provider.checkpoint
    replay = provider.finish_progress(
        _finish_at(recorded.checkpoint, _operation(1), "accepted", _digest(2)),
    )
    assert replay.outcome == "conflict"
    original = provider.finish_progress(
        _finish_at(reserved.checkpoint, _operation(1), "accepted", _digest(2)),
    )
    assert original.outcome == "already_recorded"
    assert original.checkpoint == head
    changed = provider.finish_progress(
        _finish_at(reserved.checkpoint, _operation(1), "rejected", _digest(2)),
    )
    assert changed.outcome == "conflict"
    assert provider.checkpoint == head


def test_concurrent_reserve_has_one_winner() -> None:
    provider = _factory()
    expected = provider.checkpoint
    barrier = Barrier(2)
    results: list[ReserveProgressResponse] = []
    gate = Lock()

    def reserve(slot: int) -> None:
        _ = barrier.wait(timeout=5)
        response = provider.reserve_progress(
            _reserve_at(expected, _operation(slot), "accept"),
        )
        with gate:
            results.append(response)

    _join(_spawn(reserve, 2))
    assert sorted(item.outcome for item in results) == ["conflict", "reserved"]
    assert provider.checkpoint.intent_sequence == 1


def test_concurrent_same_operation_replays_instead_of_double_append() -> None:
    provider = _factory()
    expected = provider.checkpoint
    request = _reserve_at(expected, _operation(7), "complete")
    barrier = Barrier(2)
    results: list[ReserveProgressResponse] = []
    gate = Lock()

    def reserve() -> None:
        _ = barrier.wait(timeout=5)
        response = provider.reserve_progress(request)
        with gate:
            results.append(response)

    _join([Thread(target=reserve), Thread(target=reserve)])
    assert sorted(item.outcome for item in results) == ["already_reserved", "reserved"]
    assert results[0].reservation_id == results[1].reservation_id
    assert results[0].checkpoint == results[1].checkpoint
    assert provider.checkpoint.intent_sequence == 1


def test_concurrent_finish_has_one_winner() -> None:
    provider = _factory()
    first = provider.reserve_progress(_reserve_at(provider.checkpoint, _operation(1), "accept"))
    assert first.checkpoint is not None
    second = provider.reserve_progress(_reserve_at(first.checkpoint, _operation(2), "reject"))
    assert second.checkpoint is not None
    expected = second.checkpoint
    barrier = Barrier(2)
    results: list[FinishProgressResponse] = []
    gate = Lock()

    def finish(slot: int, state: ProgressTerminalState) -> None:
        _ = barrier.wait(timeout=5)
        response = provider.finish_progress(
            _finish_at(expected, _operation(slot), state, _digest(slot)),
        )
        with gate:
            results.append(response)

    threads = [
        Thread(target=finish, args=(1, "accepted")),
        Thread(target=finish, args=(2, "rejected")),
    ]
    _join(threads)
    assert sorted(item.outcome for item in results) == ["conflict", "recorded"]
    assert provider.checkpoint.intent_sequence == 3
    winner = next(item for item in results if item.outcome == "recorded")
    assert winner.checkpoint == provider.checkpoint


def test_scope_mismatch_is_contract_error_without_mutation() -> None:
    provider = _factory()
    before = provider.checkpoint
    other = FreshnessScope(
        provider_instance_id="provider:OTHER",
        workspace_id="22222222-2222-4222-8222-222222222222",
    )
    read = ReadFreshnessRequest.model_validate(_case_request("ready")).model_copy(
        update={"scope": other},
    )
    with pytest.raises(TestOnlyContractError, match="COMPANY_CONTRACT_INVALID"):
        _ = provider.read_freshness(read)
    reserve = _reserve_at(before, _operation(1), "accept").model_copy(update={"scope": other})
    with pytest.raises(TestOnlyContractError):
        _ = provider.reserve_progress(reserve)
    finish = _finish_at(before, _operation(1), "accepted", _digest(1)).model_copy(
        update={"scope": other},
    )
    with pytest.raises(TestOnlyContractError):
        _ = provider.finish_progress(finish)
    assert provider.checkpoint == before


def test_product_tree_does_not_export_test_only_memory() -> None:
    root = Path(__file__).resolve().parents[1] / "sb"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "TestOnlyMemoryFreshnessProvider" not in text
        assert "TEST_ONLY_memory" not in text
        assert "memory_from_factory" not in text


def _dispatch(
    provider: TestOnlyMemoryFreshnessProvider,
    operation: object,
    request: JsonObject,
) -> ReadFreshnessResponse | ReserveProgressResponse | FinishProgressResponse:
    match operation:
        case "read_freshness":
            return provider.read_freshness(ReadFreshnessRequest.model_validate(request))
        case "reserve_progress":
            return provider.reserve_progress(ReserveProgressRequest.model_validate(request))
        case "finish_progress":
            return provider.finish_progress(FinishProgressRequest.model_validate(request))
        case _:
            raise AssertionError(f"unknown fixture operation: {operation!r}")


def _factory() -> TestOnlyMemoryFreshnessProvider:
    memory = _object(_load()["test_only_memory"])
    return memory_from_factory(_object(memory["factory_input"]))


def _case_request(name: str) -> JsonObject:
    memory = _object(_load()["test_only_memory"])
    cases = memory["cases"]
    if not isinstance(cases, list):
        raise TypeError("cases")
    for case in cases:
        body = _object(case)
        if body.get("name") == name:
            return _object(body["request"])
    raise AssertionError(name)


def _reserve_at(
    expected: Checkpoint,
    operation_id: str,
    operation: ProgressOperation,
) -> ReserveProgressRequest:
    return ReserveProgressRequest(
        schema_version=2,
        scope=_scope(),
        operation_id=operation_id,
        operation=operation,
        expected_checkpoint=expected,
        event_digest=_digest(1),
        challenge="challenge:TEST_ONLY:reserve:local",
    )


def _finish_at(
    expected: Checkpoint,
    operation_id: str,
    terminal_state: ProgressTerminalState,
    evidence: str,
) -> FinishProgressRequest:
    return FinishProgressRequest(
        schema_version=2,
        scope=_scope(),
        operation_id=operation_id,
        reservation_id=reservation_id_for(operation_id),
        expected_checkpoint=expected,
        evidence_digest=evidence,
        terminal_state=terminal_state,
        challenge="challenge:TEST_ONLY:finish:local",
    )


def _scope() -> FreshnessScope:
    return FreshnessScope(
        provider_instance_id="provider:TEST_ONLY",
        workspace_id="11111111-1111-4111-8111-111111111111",
    )


def _operation(slot: int) -> str:
    return "sha256:" + f"{slot:064x}"


def _digest(slot: int) -> str:
    return "sha256:" + f"{slot:064x}"


def _spawn(target: Callable[[int], None], count: int) -> list[Thread]:
    return [Thread(target=target, args=(slot,)) for slot in range(1, count + 1)]


def _join(threads: list[Thread]) -> None:
    errors: list[BaseException] = []

    def capture(args: threading.ExceptHookArgs) -> None:
        if isinstance(args.exc_value, BaseException):
            errors.append(args.exc_value)
            return
        errors.append(RuntimeError("thread failed without an exception value"))

    previous = threading.excepthook
    threading.excepthook = capture
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
    finally:
        threading.excepthook = previous
    assert errors == []


def _load() -> JsonObject:
    return _object(cast(object, json.loads(_FIXTURE.read_text(encoding="utf-8"))))


def _object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError("fixture value must be an object")
    return cast(JsonObject, value)


def _dump(
    response: ReadFreshnessResponse | ReserveProgressResponse | FinishProgressResponse,
) -> JsonObject:
    dumped = response.model_dump(mode="json")
    return _object(dumped)
