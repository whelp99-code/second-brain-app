from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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
)
from sb.effect_values import JsonValue, canonical_bytes

_PROGRESS_DOMAIN = b"second-brain/TEST_ONLY-memory-progress/v1\0"
_SHA256_PREFIX = "sha256:"
_RESERVATION_PREFIX = "reservation:TEST_ONLY:"


class TestOnlyContractError(ValueError):
    __test__: bool = False


@dataclass(frozen=True, slots=True)
class _Record:
    operation: ProgressOperation
    event_digest: str
    expected_checkpoint: Checkpoint
    reservation_id: str
    checkpoint: Checkpoint
    evidence_digest: str | None = None
    terminal_state: ProgressTerminalState | None = None
    finish_expected: Checkpoint | None = None
    finish_checkpoint: Checkpoint | None = None
    state: Literal["reserved", "finished"] = "reserved"


class TestOnlyMemoryFreshnessProvider:
    __test__: bool = False

    def __init__(self, scope: FreshnessScope, initial_checkpoint: Checkpoint) -> None:
        self._scope: FreshnessScope = scope.model_copy(deep=True)
        self._head: Checkpoint = initial_checkpoint.model_copy(deep=True)
        self._records: dict[str, _Record] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def checkpoint(self) -> Checkpoint:
        with self._lock:
            return self._head.model_copy(deep=True)

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        self._require_scope(request.scope)
        with self._lock:
            if any(record.state == "reserved" for record in self._records.values()):
                return _read(self._scope, request.challenge, "uncertain", None)
            if request.observed_checkpoint == self._head:
                return _read(self._scope, request.challenge, "ready", self._head)
            return _read(self._scope, request.challenge, "mismatch", None)

    def reserve_progress(self, request: ReserveProgressRequest) -> ReserveProgressResponse:
        self._require_scope(request.scope)
        reservation_id = reservation_id_for(request.operation_id)
        with self._lock:
            existing = self._records.get(request.operation_id)
            if existing is not None:
                if _same_reserve(existing, request):
                    return _reserve(
                        self._scope,
                        request.challenge,
                        "already_reserved",
                        existing.checkpoint,
                        existing.reservation_id,
                    )
                return _reserve(self._scope, request.challenge, "conflict", None, None)
            if request.expected_checkpoint != self._head:
                return _reserve(self._scope, request.challenge, "conflict", None, None)
            record = {
                "event_digest": request.event_digest,
                "operation": request.operation,
                "operation_id": request.operation_id,
                "reservation_id": reservation_id,
                "state": "reserved",
            }
            checkpoint = _advance(self._head, record)
            self._records[request.operation_id] = _Record(
                operation=request.operation,
                event_digest=request.event_digest,
                expected_checkpoint=request.expected_checkpoint,
                reservation_id=reservation_id,
                checkpoint=checkpoint,
            )
            self._head = checkpoint
            return _reserve(
                self._scope,
                request.challenge,
                "reserved",
                checkpoint,
                reservation_id,
            )

    def finish_progress(self, request: FinishProgressRequest) -> FinishProgressResponse:
        self._require_scope(request.scope)
        _ = reservation_id_for(request.operation_id)
        with self._lock:
            existing = self._records.get(request.operation_id)
            if existing is None or existing.reservation_id != request.reservation_id:
                return _finish(self._scope, request.challenge, "conflict", None)
            if request.terminal_state != TERMINAL_STATE_BY_OPERATION[existing.operation]:
                return _finish(self._scope, request.challenge, "conflict", None)
            if existing.state == "finished":
                if _same_finish(existing, request):
                    return _finish(
                        self._scope,
                        request.challenge,
                        "already_recorded",
                        existing.finish_checkpoint,
                    )
                return _finish(self._scope, request.challenge, "conflict", None)
            if request.expected_checkpoint != self._head:
                return _finish(self._scope, request.challenge, "conflict", None)
            body = {
                "evidence_digest": request.evidence_digest,
                "operation_id": request.operation_id,
                "reservation_id": request.reservation_id,
                "state": "finished",
                "terminal_state": request.terminal_state,
            }
            checkpoint = _advance(self._head, body)
            self._records[request.operation_id] = _Record(
                operation=existing.operation,
                event_digest=existing.event_digest,
                expected_checkpoint=existing.expected_checkpoint,
                reservation_id=existing.reservation_id,
                checkpoint=existing.checkpoint,
                evidence_digest=request.evidence_digest,
                terminal_state=request.terminal_state,
                finish_expected=request.expected_checkpoint,
                finish_checkpoint=checkpoint,
                state="finished",
            )
            self._head = checkpoint
            return _finish(self._scope, request.challenge, "recorded", checkpoint)

    def _require_scope(self, scope: FreshnessScope) -> None:
        if scope != self._scope:
            raise TestOnlyContractError("COMPANY_CONTRACT_INVALID")


def test_only_memory_provider(
    scope: FreshnessScope,
    initial_checkpoint: Checkpoint,
) -> TestOnlyMemoryFreshnessProvider:
    return TestOnlyMemoryFreshnessProvider(scope, initial_checkpoint)


def memory_from_factory(
    factory_input: Mapping[str, JsonValue],
) -> TestOnlyMemoryFreshnessProvider:
    scope = factory_input.get("scope")
    initial = factory_input.get("initial_checkpoint")
    if not isinstance(scope, dict) or not isinstance(initial, dict):
        raise TestOnlyContractError("COMPANY_CONTRACT_INVALID")
    return TestOnlyMemoryFreshnessProvider(
        FreshnessScope.model_validate(scope),
        Checkpoint.model_validate(initial),
    )


def reservation_id_for(operation_id: str) -> str:
    digest = operation_id.removeprefix(_SHA256_PREFIX)
    if (
        not operation_id.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise TestOnlyContractError("COMPANY_CONTRACT_INVALID")
    return _RESERVATION_PREFIX + digest


def _same_reserve(existing: _Record, request: ReserveProgressRequest) -> bool:
    return (
        existing.operation == request.operation
        and existing.event_digest == request.event_digest
        and existing.expected_checkpoint == request.expected_checkpoint
    )


def _same_finish(existing: _Record, request: FinishProgressRequest) -> bool:
    return (
        existing.evidence_digest == request.evidence_digest
        and existing.terminal_state == request.terminal_state
        and existing.finish_expected == request.expected_checkpoint
        and existing.finish_checkpoint is not None
    )


def _advance(head: Checkpoint, record: Mapping[str, JsonValue]) -> Checkpoint:
    sequence = head.intent_sequence + 1
    payload: dict[str, JsonValue] = {
        "previous_root": head.intent_root,
        "sequence": sequence,
        "record": dict(record),
    }
    root = _SHA256_PREFIX + hashlib.sha256(_PROGRESS_DOMAIN + canonical_bytes(payload)).hexdigest()
    return head.model_copy(update={"intent_sequence": sequence, "intent_root": root})


def _read(
    scope: FreshnessScope,
    challenge: str,
    status: Literal["ready", "mismatch", "uncertain"],
    checkpoint: Checkpoint | None,
) -> ReadFreshnessResponse:
    return ReadFreshnessResponse(
        schema_version=2,
        scope=scope,
        challenge=challenge,
        status=status,
        checkpoint=None if checkpoint is None else checkpoint.model_copy(deep=True),
    )


def _reserve(
    scope: FreshnessScope,
    challenge: str,
    outcome: Literal["reserved", "already_reserved", "conflict"],
    checkpoint: Checkpoint | None,
    reservation_id: str | None,
) -> ReserveProgressResponse:
    return ReserveProgressResponse(
        schema_version=2,
        scope=scope,
        challenge=challenge,
        outcome=outcome,
        checkpoint=None if checkpoint is None else checkpoint.model_copy(deep=True),
        reservation_id=reservation_id,
    )


def _finish(
    scope: FreshnessScope,
    challenge: str,
    outcome: Literal["recorded", "already_recorded", "conflict"],
    checkpoint: Checkpoint | None,
) -> FinishProgressResponse:
    return FinishProgressResponse(
        schema_version=2,
        scope=scope,
        challenge=challenge,
        outcome=outcome,
        checkpoint=None if checkpoint is None else checkpoint.model_copy(deep=True),
    )
