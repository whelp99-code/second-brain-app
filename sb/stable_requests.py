"""Stable V1/V3 remember publication, replay and original acceptance recovery."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from collections.abc import Callable
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
from sb.request_store import ReplayConflict, RequestIdentity, RequestStore
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)
from sb.write_request_values import (
    MAX_ENVELOPE_BYTES,
    JsonValue,
    digest,
    parse_remember_envelope,
    parse_request,
    parse_request_v3,
)


class StableRequestError(ValueError):
    pass


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
    validate_recovery: Callable[[bytes, bytes], None] | None = None
    max_bytes: int = MAX_ENVELOPE_BYTES


def _recover_publication(path: Path, expected: bytes, *, links: int = 1,
    validate_recovery: Callable[[bytes, bytes], None] | None = None, max_bytes: int = MAX_ENVELOPE_BYTES) -> bytes:
    """Adopt only an exact earlier request, retaining its original acceptance."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not safe_request_file(before, links) or before.st_size > max_bytes:
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        payload = bytearray()
        while len(payload) <= max_bytes:
            block = os.read(fd, max_bytes + 1 - len(payload))
            if not block:
                break
            payload.extend(block)
        after = os.fstat(fd)
        visible = path.stat(follow_symlinks=False)
        if (not safe_request_file(after, links) or not safe_request_file(visible, links)
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                != (visible.st_dev, visible.st_ino, visible.st_size, visible.st_mtime_ns, visible.st_ctime_ns)
                or len(payload) > max_bytes):
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        if validate_recovery is not None:
            validate_recovery(bytes(payload), expected)
            return bytes(payload)
        original = parse_remember_envelope(bytes(payload))
        current = parse_remember_envelope(expected)
        if (original.request != current.request or original.schema_version != current.schema_version
                or parse_instant(original.accepted_at) > parse_instant(current.accepted_at)):
            raise StableRequestError("WRITE_REQUEST_REPLAY_CONFLICT")
        return bytes(payload)
    finally:
        os.close(fd)


def _publish(directory: Path, publication: _PendingPublication) -> bytes:
    def recover(path: Path, expected: bytes, *, links: int = 1) -> bytes:
        return _recover_publication(path, expected, links=links,
            validate_recovery=publication.validate_recovery, max_bytes=publication.max_bytes)

    if len(publication.payload) > publication.max_bytes:
        raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
    name = publication.name
    payload = publication.payload
    directory_fd = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    metadata = os.fstat(directory_fd)
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        os.close(directory_fd)
        raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    file_fd: int | None = None
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        owned_temps = tuple(directory.glob(f".{name}.*.tmp"))
        if len(owned_temps) > 1:
            raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
        if (directory / name).exists():
            final_meta = (directory / name).stat(follow_symlinks=False)
            linked = final_meta.st_nlink == 2 and len(owned_temps) == 1
            if linked:
                if not owned_temps:
                    raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                temp_meta = owned_temps[0].stat(follow_symlinks=False)
                if (temp_meta.st_dev, temp_meta.st_ino) != (final_meta.st_dev, final_meta.st_ino):
                    raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
            links = 2 if linked else 1
            payload = recover(directory / name, payload, links=links)
            for candidate in owned_temps:
                if recover(candidate, payload, links=links) != payload:
                    raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                candidate.unlink()
                os.fsync(directory_fd)
            return payload
        if owned_temps:
            candidate = owned_temps[0]
            payload = recover(candidate, payload)
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
        return payload
    except FileExistsError:
        return recover(directory / name, payload)
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
        payload = _publish(
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
