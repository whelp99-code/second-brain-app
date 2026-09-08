"""Descriptor-relative stable publication for authenticated V2 effect requests.
# noqa: SIZE_OK -- one atomic descriptor-relative publication boundary
"""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.effect_values import (
    JsonValue,
    canonical_bytes,
    format_instant,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.effect_write_models import MemoryEffectWriteAcceptedV2, MemoryEffectWriteRequestV2
from sb.effect_write_values import (
    MAX_EFFECT_FILE_BYTES,
    EffectRequestRejected,
    model_object,
    parse_effect_request,
    request_file_digest,
)
from sb.request_store import ReplayConflict, RequestIdentity, RequestStore, RequestStoreError
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)


class EffectWriteIoError(ValueError):
    pass


def _safe_directory(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _safe_file(metadata: os.stat_result, links: int = 1) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == links
    )


def open_request_directory(path: Path) -> int:
    try:
        preview = path.stat(follow_symlinks=False)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        observed = os.fstat(descriptor)
    except OSError as exc:
        raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE") from exc
    if (
        not _safe_directory(preview)
        or not _safe_directory(observed)
        or preview.st_dev != observed.st_dev
        or preview.st_ino != observed.st_ino
    ):
        os.close(descriptor)
        raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
    return descriptor


def _read_file(directory: int, name: str) -> bytes:
    descriptor: int | None = None
    try:
        preview = os.stat(name, dir_fd=directory, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        observed = os.fstat(descriptor)
        if not _safe_file(preview) or not _safe_file(observed):
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        if preview.st_dev != observed.st_dev or preview.st_ino != observed.st_ino:
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_EFFECT_FILE_BYTES:
            block = os.read(descriptor, min(65_536, MAX_EFFECT_FILE_BYTES + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        if size > MAX_EFFECT_FILE_BYTES:
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        return b"".join(chunks)
    except OSError as exc:
        raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class _PendingPublication:
    final: str
    payload: bytes
    emitter: BoundBarrierEmitter


def _publish(directory: int, publication: _PendingPublication) -> None:
    final = publication.final
    payload = publication.payload
    temporary = f".{final}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise EffectWriteIoError("WRITE_REQUEST_IO_FAILED")
            written += count
        os.fsync(descriptor)
        publication.emitter.emit("request_temp_write")
        before = os.fstat(descriptor)
        if not _safe_file(before):
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        os.link(
            temporary,
            final,
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
        linked = True
        after = os.fstat(descriptor)
        visible = os.stat(final, dir_fd=directory, follow_symlinks=False)
        if not _safe_file(after, 2) or not _safe_file(visible, 2):
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        if before.st_dev != after.st_dev or before.st_ino != after.st_ino:
            raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
        os.fsync(directory)
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
        publication.emitter.emit("pending_publish_fsync")
    except FileExistsError:
        raise
    except OSError as exc:
        raise EffectWriteIoError("WRITE_REQUEST_IO_FAILED") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            temporary = ""
        if linked:
            metadata = os.stat(final, dir_fd=directory, follow_symlinks=False)
            if metadata.st_nlink != 1:
                raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")


def _identity(request: MemoryEffectWriteRequestV2) -> RequestIdentity:
    delegation = request.delegation
    payload_digest = delegation.payload_digest
    return RequestIdentity(
        schema_version=2,
        request_id=request.request_id,
        request_digest=request.request_digest,
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        lane_id=request.lane_id,
        operation=request.operation,
        payload_digest=payload_digest,
        target_manifest_digest=request.target_manifest_digest,
        scope_digest=request.scope_digest,
        delegation_id=delegation.delegation_id,
        delegation_digest=delegation.delegation_digest,
        delegation_nonce=delegation.nonce,
        tombstone_sequence=request.tombstone_high_water.sequence,
        tombstone_set_root=request.tombstone_high_water.set_root,
    )


def _result(
    request: MemoryEffectWriteRequestV2,
    accepted_at: str,
    file_digest: str,
    replayed: bool,
) -> MemoryEffectWriteAcceptedV2:
    return MemoryEffectWriteAcceptedV2(
        schema_version=2,
        kind="accepted",
        state="pending",
        request_id=request.request_id,
        request_digest=request.request_digest,
        idempotency_key=request.idempotency_key,
        envelope_digest=request.envelope_digest,
        lane=request.lane,
        operation=request.operation,
        accepted_at=accepted_at,
        queue_locator=f"pending/{request.request_id}.v2.json",
        request_file_digest=file_digest,
        replayed=replayed,
        capability_verified=True,
        tombstone_sequence=request.tombstone_high_water.sequence,
        tombstone_set_root=request.tombstone_high_water.set_root,
        provider_instance_id=request.provider_instance_id,
    )


def accept_effect_request(
    root: Path,
    value: JsonValue,
    accepted_at: datetime,
    *,
    public_keys: Mapping[str, Ed25519PublicKey] | None = None,
    provider_instance_id: str | None = None,
    revoked_delegations: AbstractSet[str] | None = None,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None = None,
    barrier_sink: Task30BarrierSink | None = None,
) -> MemoryEffectWriteAcceptedV2:
    """Verify, atomically publish, and globally journal one V2 request."""
    stamp = format_instant(accepted_at)
    request = parse_effect_request(
        value,
        now=stamp,
        public_keys=public_keys,
        expected_provider=provider_instance_id,
        external_public_keys=external_public_keys,
    )
    if revoked_delegations is not None and request.delegation.delegation_id in revoked_delegations:
        raise EffectRequestRejected("EFFECT_DELEGATION_INVALID", request.request_id)
    try:
        store = RequestStore(root)
    except RequestStoreError as exc:
        raise EffectWriteIoError(str(exc)) from exc
    directory = open_request_directory(store.pending)
    final = f"{request.request_id}.v2.json"
    envelope = {
        "schema_version": 2,
        "state": "pending",
        "accepted_at": stamp,
        "request": model_object(request),
    }
    payload = canonical_bytes(envelope) + b"\n"
    if len(payload) > MAX_EFFECT_FILE_BYTES:
        store.close()
        os.close(directory)
        raise EffectRequestRejected("EFFECT_REQUEST_OVERSIZE", request.request_id)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        identity = _identity(request)
        previous = store.replay_status(identity)
        if previous is not None:
            loaded = strict_loads(previous.result_json, MAX_EFFECT_FILE_BYTES)
            if not is_json_object(loaded):
                raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
            replay = MemoryEffectWriteAcceptedV2.model_validate(loaded)
            return replay.model_copy(update={"replayed": True})
        high_sequence, high_root = store.tombstone_high_water()
        delta = [model_object(entry) for entry in request.tombstone_chain_delta]
        if delta:
            first = request.tombstone_chain_delta[0]
            last = request.tombstone_chain_delta[-1]
            valid_high_water = first.sequence == high_sequence + 1
            valid_high_water = valid_high_water and first.previous_root == high_root
            valid_high_water = valid_high_water and last.sequence == request.tombstone_high_water.sequence
            valid_high_water = valid_high_water and last.set_root == request.tombstone_high_water.set_root
        else:
            valid_high_water = high_sequence == request.tombstone_high_water.sequence
            valid_high_water = valid_high_water and high_root == request.tombstone_high_water.set_root
        if not valid_high_water:
            raise EffectRequestRejected("EFFECT_TOMBSTONE_STALE", request.request_id)
        try:
            _publish(
                directory,
                _PendingPublication(
                    final,
                    payload,
                    BoundBarrierEmitter(
                        barrier_sink or NoopBarrierSink(),
                        BarrierContext(request.request_id),
                    ),
                ),
            )
        except FileExistsError:
            existing = _read_file(directory, final)
            loaded = strict_loads(existing, MAX_EFFECT_FILE_BYTES)
            if not is_json_object(loaded) or loaded.get("request") != model_object(request):
                raise ReplayConflict("WRITE_REQUEST_REPLAY_CONFLICT") from None
            existing_accepted = loaded.get("accepted_at")
            if not isinstance(existing_accepted, str):
                raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
            stamp = existing_accepted
        file_digest = request_file_digest(request, stamp)
        accepted = _result(request, stamp, file_digest, False)
        status, replayed = store.accept(
            identity,
            model_object(accepted),
            parse_instant(stamp),
            tombstones=delta,
            tombstone_targets=[model_object(target) for target in request.targets] if delta else None,
        )
        if replayed:
            loaded = strict_loads(status.result_json, MAX_EFFECT_FILE_BYTES)
            if not is_json_object(loaded):
                raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE")
            result = MemoryEffectWriteAcceptedV2.model_validate(loaded)
            return result.model_copy(update={"replayed": True})
        return accepted
    finally:
        fcntl.flock(directory, fcntl.LOCK_UN)
        os.close(directory)
        store.close()
