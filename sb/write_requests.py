from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
import stat
import subprocess
from collections.abc import Set as AbstractSet
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.contracts import (
    Digest,
    ExpectedPriorV1,
    MemoryWriteInboxEnvelopeV1,
    MemoryWriteRequestV1,
    MemoryWriteResultV1,
)
from sb.effect_values import is_json_object
from sb.effect_write_models import MemoryEffectWriteAcceptedV2
from sb.effect_write_requests import accept_effect_request
from sb.page_ids import git_rel
from sb.stable_requests import StableRequestError, accept_stable_v1_request
from sb.write_request_values import (
    MAX_ENVELOPE_BYTES,
    JsonValue,
    WriteRequestRejected,
    canonical_bytes,
    digest,
    parse_envelope_bytes,
    parse_request,
    reject,
)

FINAL_NAME: Final = re.compile(r"memreq:pos:v1:[0-9a-f]{64}\.json\Z")
TEMP_NAME: Final = re.compile(r"\.memreq:pos:v1:[0-9a-f]{64}\.[0-9]+\.[0-9a-f]{32}\.tmp\Z")

__all__: Final = (
    "WriteRequestRejected",
    "accept_memory_write_request",
    "accept_write_request",
)


def _check_prior(root: Path, prior: ExpectedPriorV1 | None) -> None:
    if prior is None:
        return
    path = git_rel(prior.source_id)
    oid = subprocess.run(
        ["git", "rev-parse", f"HEAD:{path}"], cwd=root, check=False, capture_output=True
    ).stdout.decode().strip()
    blob = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{path}"], cwd=root, check=False, capture_output=True
    )
    if blob.returncode != 0:
        reject("WRITE_REQUEST_PRIOR_NOT_FOUND")
    observed = "sha256:" + hashlib.sha256(blob.stdout).hexdigest()
    if prior.source_version != f"git:{oid}" or prior.source_digest != observed:
        reject("WRITE_REQUEST_PRIOR_MISMATCH")


def _same(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_uid == right.st_uid
        and stat.S_IMODE(left.st_mode) == stat.S_IMODE(right.st_mode)
    )


def _safe_dir(metadata: os.stat_result) -> bool:
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


def _open_pending(root: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        preview = os.stat(root, follow_symlinks=False)
        current = os.open(root, flags)
    except OSError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INBOX_UNSAFE") from exc
    try:
        if not _safe_dir(preview) or not _same(preview, os.fstat(current)):
            reject("WRITE_REQUEST_INBOX_UNSAFE")
        for name in ("inbox", ".requests", "pending"):
            preview = os.stat(name, dir_fd=current, follow_symlinks=False)
            child = os.open(name, flags, dir_fd=current)
            observed = os.fstat(child)
            if not _safe_dir(preview) or not _same(preview, observed):
                os.close(child)
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            os.close(current)
            current = child
        return current
    except WriteRequestRejected:
        os.close(current)
        raise
    except OSError as exc:
        os.close(current)
        raise WriteRequestRejected("WRITE_REQUEST_INBOX_UNSAFE") from exc


def _result(
    request: MemoryWriteRequestV1, accepted: str, request_file_digest: Digest, replayed: bool
) -> MemoryWriteResultV1:
    return MemoryWriteResultV1(
        1,
        "accepted",
        "pending",
        request.candidate_id,
        request.request_id,
        request.request_digest,
        request.idempotency_key,
        request.operation,
        accepted,
        f"inbox/.requests/pending/{request.request_id}.json",
        request_file_digest,
        replayed,
    )


def _visible_envelope(directory: int, name: str) -> MemoryWriteInboxEnvelopeV1:
    fd: int | None = None
    try:
        preview = os.stat(name, dir_fd=directory, follow_symlinks=False)
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        before = os.fstat(fd)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_ENVELOPE_BYTES:
            block = os.read(fd, min(65_536, MAX_ENVELOPE_BYTES + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        after = os.fstat(fd)
        observed = os.stat(name, dir_fd=directory, follow_symlinks=False)
        safe = _safe_file(preview) and _same(preview, before) and _same(before, after)
        safe = safe and _safe_file(observed) and _same(after, observed)
        if not safe or size > MAX_ENVELOPE_BYTES:
            reject("WRITE_REQUEST_INBOX_UNSAFE")
        envelope = parse_envelope_bytes(b"".join(chunks))
        if name != f"{envelope.request.request_id}.json":
            reject("WRITE_REQUEST_INBOX_UNSAFE")
        return envelope
    except (OSError, WriteRequestRejected) as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INBOX_UNSAFE") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _scan_pending(directory: int, request: MemoryWriteRequestV1) -> MemoryWriteResultV1 | None:
    before = os.fstat(directory)
    try:
        names = os.listdir(directory)
    except OSError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INBOX_UNSAFE") from exc
    if len(names) > 1_024:
        reject("WRITE_REQUEST_INBOX_UNSAFE")
    replay: MemoryWriteInboxEnvelopeV1 | None = None
    conflict = False
    for name in names:
        if name.startswith("."):
            if TEMP_NAME.fullmatch(name) is None:
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            continue
        if FINAL_NAME.fullmatch(name) is None:
            reject("WRITE_REQUEST_INBOX_UNSAFE")
        envelope = _visible_envelope(directory, name)
        existing = envelope.request
        if existing == request:
            replay = envelope
            continue
        same_key = existing.idempotency_key == request.idempotency_key
        digest_alias = (
            existing.candidate_id == request.candidate_id
            and existing.operation == request.operation
            and existing.request_digest == request.request_digest
        )
        conflict = conflict or same_key or digest_alias
    if not _same(before, os.fstat(directory)):
        reject("WRITE_REQUEST_INBOX_UNSAFE")
    if conflict:
        reject("WRITE_REQUEST_REPLAY_CONFLICT")
    if replay is None:
        return None
    return _result(
        replay.request,
        replay.accepted_at,
        digest("file", asdict(replay)),
        True,
    )


def accept_write_request(root: Path, value: JsonValue, now: datetime) -> MemoryWriteResultV1:
    request = parse_request(value, now)
    _check_prior(root, request.expected_prior)
    accepted = now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    envelope = MemoryWriteInboxEnvelopeV1(1, "pending", accepted, request)
    payload = canonical_bytes(asdict(envelope)) + b"\n"
    if len(payload) > MAX_ENVELOPE_BYTES:
        reject("WRITE_REQUEST_OVERSIZE")
    request_file_digest = digest("file", asdict(envelope))
    directory = _open_pending(root)
    final = f"{request.request_id}.json"
    temporary = f".{request.request_id}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    fd: int | None = None
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        replay = _scan_pending(directory, request)
        if replay is not None:
            return replay
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(temporary, flags, 0o600, dir_fd=directory)
            written = 0
            while written < len(payload):
                count = os.write(fd, payload[written:])
                if count <= 0:
                    reject("WRITE_REQUEST_IO_FAILED")
                written += count
            os.fsync(fd)
            before_link = os.fstat(fd)
            if not _safe_file(before_link):
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            os.link(
                temporary,
                final,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            after_link = os.fstat(fd)
            final_metadata = os.stat(final, dir_fd=directory, follow_symlinks=False)
            if not _same(before_link, after_link) or not _same(after_link, final_metadata):
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            if not _safe_file(after_link, links=2) or not _safe_file(final_metadata, links=2):
                reject("WRITE_REQUEST_INBOX_UNSAFE")
        except FileExistsError:
            replay = _scan_pending(directory, request)
            if replay is None:
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            return replay
        os.fsync(directory)
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
        return _result(request, accepted, request_file_digest, False)
    except WriteRequestRejected:
        raise
    except OSError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_IO_FAILED") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            temporary = ""
        os.close(directory)


def accept_memory_write_request(
    vault_root: Path,
    request_root: Path,
    value: object,
    now: datetime,
    *,
    public_keys: dict[str, Ed25519PublicKey] | None = None,
    provider_instance_id: str | None = None,
    revoked_delegations: AbstractSet[str] | None = None,
    external_public_keys: dict[str, Ed25519PublicKey] | None = None,
) -> MemoryWriteResultV1 | MemoryEffectWriteAcceptedV2:
    """Dispatch the exact V1/V2 discriminated union without mutating V1 bytes."""
    if not is_json_object(value):
        reject("WRITE_REQUEST_INVALID")
    schema_version = value.get("schema_version")
    if schema_version == 1:
        try:
            return accept_stable_v1_request(request_root, value, now)
        except StableRequestError as exc:
            raise WriteRequestRejected(str(exc)) from exc
    if schema_version == 2:
        del vault_root
        try:
            return accept_effect_request(
                request_root,
                value,
                now,
                public_keys=public_keys,
                provider_instance_id=provider_instance_id,
                revoked_delegations=revoked_delegations,
                external_public_keys=external_public_keys,
            )
        except ValueError as exc:
            raise WriteRequestRejected(str(exc)) from exc
    reject("WRITE_REQUEST_INVALID")
