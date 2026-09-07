"""Stable Task 29 V1 queue compatibility and one-time legacy import."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sb.contracts import (
    Digest,
    MemoryWriteInboxEnvelopeV1,
    MemoryWriteRequestV1,
    MemoryWriteResultV1,
    WriteOperation,
)
from sb.effect_values import canonical_bytes, format_instant, is_json_object, strict_loads
from sb.request_store import ReplayConflict, RequestIdentity, RequestStore
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)
from sb.write_request_values import JsonValue, digest, parse_request


class StableRequestError(ValueError):
    pass


def _identity(request: MemoryWriteRequestV1) -> RequestIdentity:
    return RequestIdentity(
        schema_version=1,
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
    value["schema_version"] = 1
    receipt = value.get("receipt")
    if isinstance(receipt, dict):
        value["receipt"] = {"schema_version": 1, **receipt}
    return value


def _result(
    request: MemoryWriteRequestV1,
    accepted_at: str,
    request_file_digest: str,
    replayed: bool,
) -> MemoryWriteResultV1:
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


def safe_request_file(metadata: os.stat_result, links: int = 1) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == links
    )


@dataclass(frozen=True, slots=True)
class _PendingPublication:
    name: str
    payload: bytes
    emitter: BoundBarrierEmitter


def _publish(directory: Path, publication: _PendingPublication) -> None:
    name = publication.name
    payload = publication.payload
    directory_fd = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    file_fd: int | None = None
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        owned_temps = tuple(directory.glob(f".{name}.*.tmp"))
        if len(owned_temps) > 1:
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        if (directory / name).exists():
            for candidate in owned_temps:
                if not safe_request_file(candidate.stat(follow_symlinks=False)) or candidate.read_bytes() != payload:
                    raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                candidate.unlink()
                os.fsync(directory_fd)
            return
        if owned_temps:
            candidate = owned_temps[0]
            if not safe_request_file(candidate.stat(follow_symlinks=False)) or candidate.read_bytes() != payload:
                raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            temporary = candidate.name
            file_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        else:
            file_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
            written = 0
            while written < len(payload):
                count = os.write(file_fd, payload[written:])
                if count <= 0:
                    raise StableRequestError("WRITE_REQUEST_IO_FAILED")
                written += count
            os.fsync(file_fd)
            publication.emitter.emit("request_temp_write")
        if not safe_request_file(os.fstat(file_fd)):
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        os.link(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if not safe_request_file(os.fstat(file_fd), 2):
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        os.fsync(directory_fd)
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        publication.emitter.emit("pending_publish_fsync")
    except FileExistsError:
        return
    finally:
        if file_fd is not None:
            os.close(file_fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            temporary = ""
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        os.close(directory_fd)


def accept_stable_v1_request(
    request_root: Path,
    value: JsonValue,
    now: datetime,
    barrier_sink: Task30BarrierSink | None = None,
) -> MemoryWriteResultV1:
    request = parse_request(value, now)
    if request.operation is not WriteOperation.REMEMBER:
        raise StableRequestError("REAPPROVAL_REQUIRED")
    stamp = format_instant(now)
    envelope = asdict(MemoryWriteInboxEnvelopeV1(1, "pending", stamp, request))
    file_digest = digest("file", envelope)
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
        final = store.pending / f"{request.request_id}.v1.json"
        _publish(
            store.pending,
            _PendingPublication(
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
        status, replayed = store.accept(identity, asdict(result), now)
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
