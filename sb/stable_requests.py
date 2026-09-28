"""Stable V1/V3 remember publication, replay and original acceptance recovery."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sb.contracts import (
    Digest,
    MemoryWriteInboxEnvelopeV1,
    MemoryWriteRequestV1,
    MemoryWriteResultV1,
    WriteOperation,
)
from sb.effect_values import (
    canonical_bytes,
    format_instant,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.remember_contracts import (
    MemoryWriteInboxEnvelopeV3,
    MemoryWriteRequestV3,
    MemoryWriteResultV3,
)
from sb.request_publication import (
    PendingPublication,
    StableRequestError,
    publish_pending,
    recover_publication,
    safe_request_file,
)
from sb.request_store import ReplayConflict, RequestIdentity, RequestStore
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)
from sb.write_request_values import (
    JsonValue,
    digest,
    parse_remember_envelope,
    parse_request,
    parse_request_v3,
)

__all__ = (
    "PendingPublication",
    "StableRequestError",
    "accept_stable_v1_request",
    "accept_stable_v3_request",
    "publish_pending",
    "recover_publication",
    "request_value",
    "safe_request_file",
)


def _identity(request: MemoryWriteRequestV1) -> RequestIdentity:
    return RequestIdentity(
        schema_version=3 if isinstance(request, MemoryWriteRequestV3) else 1,
        request_id=str(request.request_id),
        request_digest=str(request.request_digest),
        envelope_digest=None,
        idempotency_key=request.idempotency_key,
        lane_id=f"legacy:{request.candidate_id}:{request.operation.value}",
        operation=request.operation.value,
        payload_digest=None,
        target_manifest_digest=None,
        scope_digest=None,
        delegation_id=None,
        delegation_digest=None,
        delegation_nonce=None,
        tombstone_sequence=0,
        tombstone_set_root=(
            "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
        ),
    )


def request_value(request: MemoryWriteRequestV1) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = asdict(request)
    value["schema_version"] = 3 if isinstance(request, MemoryWriteRequestV3) else 1
    receipt = value.get("receipt")
    if isinstance(receipt, dict):
        value["receipt"] = {"schema_version": 1, **receipt}
    return value


def _result(
    request: MemoryWriteRequestV1,
    accepted_at: str,
    request_file_digest: str,
    replayed: bool,
) -> MemoryWriteResultV1 | MemoryWriteResultV3:
    values = (
        "accepted", "pending", request.candidate_id, request.request_id,
        request.request_digest, request.idempotency_key, request.operation, accepted_at,
        f"inbox/.requests/pending/{request.request_id}.json", Digest(request_file_digest), replayed,
    )
    if isinstance(request, MemoryWriteRequestV3):
        return MemoryWriteResultV3(3, *values)
    return MemoryWriteResultV1(
        schema_version=1,
        kind="accepted",
        state="pending",
        candidate_id=request.candidate_id,
        request_id=request.request_id,
        request_digest=request.request_digest,
        idempotency_key=request.idempotency_key,
        operation=request.operation,
        accepted_at=accepted_at,
        inbox_path=f"inbox/.requests/pending/{request.request_id}.json",
        request_file_digest=Digest(request_file_digest),
        replayed=replayed,
    )


def accept_stable_v1_request(
    request_root: Path,
    value: JsonValue,
    now: datetime,
    barrier_sink: Task30BarrierSink | None = None,
) -> MemoryWriteResultV1:
    request = parse_request(value, now)
    result = _accept_stable_remember(request_root, request, now, barrier_sink)
    assert isinstance(result, MemoryWriteResultV1)
    return result


def accept_stable_v3_request(
    request_root: Path,
    value: JsonValue,
    now: datetime,
    barrier_sink: Task30BarrierSink | None = None,
) -> MemoryWriteResultV3:
    request = parse_request_v3(value, now)
    result = _accept_stable_remember(request_root, request, now, barrier_sink)
    assert isinstance(result, MemoryWriteResultV3)
    return result


def _accept_stable_remember(
    request_root: Path,
    request: MemoryWriteRequestV1,
    now: datetime,
    barrier_sink: Task30BarrierSink | None,
) -> MemoryWriteResultV1 | MemoryWriteResultV3:
    if request.operation is not WriteOperation.REMEMBER:
        raise StableRequestError("REAPPROVAL_REQUIRED")
    stamp = format_instant(now)
    version = 3 if isinstance(request, MemoryWriteRequestV3) else 1
    envelope = asdict(MemoryWriteInboxEnvelopeV3(3, "pending", stamp, request)) if isinstance(
        request, MemoryWriteRequestV3
    ) else asdict(MemoryWriteInboxEnvelopeV1(1, "pending", stamp, request))
    file_digest = digest("file_v3" if version == 3 else "file", envelope)
    result = _result(request, stamp, file_digest, False)
    store = RequestStore(request_root)
    try:
        identity = _identity(request)
        previous = store.replay_status(identity)
        if previous is not None:
            loaded = strict_loads(previous.result_json, 17_408)
            if not is_json_object(loaded):
                raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            accepted_value = loaded.get("accepted_at")
            digest_value = loaded.get("request_file_digest")
            if not isinstance(accepted_value, str) or not isinstance(digest_value, str):
                raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            return _result(request, accepted_value, digest_value, True)
        payload = canonical_bytes(envelope) + b"\n"
        final = store.pending / f"{request.request_id}.v{version}.json"
        payload = publish_pending(
            store.pending,
            PendingPublication(
                final.name,
                payload,
                BoundBarrierEmitter(
                    barrier_sink or NoopBarrierSink(),
                    BarrierContext(str(request.request_id)),
                ),
            ),
        )
        metadata = final.stat(follow_symlinks=False)
        if not safe_request_file(metadata) or final.read_bytes() != payload:
            raise StableRequestError("WRITE_REQUEST_REPLAY_CONFLICT")
        published = parse_remember_envelope(payload)
        stamp = published.accepted_at
        file_digest = digest("file_v3" if version == 3 else "file", asdict(published))
        result = _result(request, stamp, file_digest, False)
        status, replayed = store.accept(identity, asdict(result), parse_instant(stamp))
        if replayed:
            loaded = strict_loads(status.result_json, 17_408)
            if not is_json_object(loaded):
                raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            accepted_value = loaded.get("accepted_at")
            digest_value = loaded.get("request_file_digest")
            if not isinstance(accepted_value, str) or not isinstance(digest_value, str):
                raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            return _result(request, accepted_value, digest_value, True)
        return result
    except ReplayConflict as exc:
        raise StableRequestError("WRITE_REQUEST_REPLAY_CONFLICT") from exc
    finally:
        store.close()
