"""Descriptor-safe pending memory-write request publication."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sb.contracts import (
    Digest,
    ExpectedPriorV1,
    MemoryWriteInboxEnvelopeV1,
    MemoryWriteRequestV1,
    MemoryWriteResultV1,
)
from sb.write_request_values import (
    MAX_ENVELOPE_BYTES,
    JsonValue,
    WriteRequestRejected,
    canonical_bytes,
    digest,
    parse_request,
    reject,
)

__all__: Final = ("WriteRequestRejected", "accept_write_request")


def _check_prior(root: Path, prior: ExpectedPriorV1 | None) -> None:
    if prior is None:
        return
    path = f"{prior.source_id}.md"
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


def _open_pending(root: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current = os.open(root, flags)
    except OSError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INBOX_UNSAFE") from exc
    try:
        for name in ("inbox", ".requests", "pending"):
            metadata = os.fstat(current)
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            child = os.open(name, flags, dir_fd=current)
            os.close(current)
            current = child
        metadata = os.fstat(current)
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            reject("WRITE_REQUEST_INBOX_UNSAFE")
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


def _read_replay(directory: int, final: str, request: MemoryWriteRequestV1) -> MemoryWriteResultV1:
    fd = os.open(final, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    try:
        metadata = os.fstat(fd)
        existing = os.read(fd, MAX_ENVELOPE_BYTES + 1)
    finally:
        os.close(fd)
    match = re.match(rb'^\{"accepted_at":"([^"]+)"', existing)
    accepted = match.group(1).decode() if match is not None else ""
    envelope = MemoryWriteInboxEnvelopeV1(1, "pending", accepted, request)
    expected = canonical_bytes(asdict(envelope)) + b"\n"
    unsafe = not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
    unsafe = unsafe or metadata.st_nlink != 1 or bool(metadata.st_mode & 0o077)
    if unsafe or existing != expected:
        reject("WRITE_REQUEST_REPLAY_CONFLICT")
    return _result(request, accepted, digest("file", asdict(envelope)), True)


def accept_write_request(root: Path, value: JsonValue, now: datetime) -> MemoryWriteResultV1:
    """Validate and atomically publish one pending request without overwrite."""
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
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(temporary, flags, 0o600, dir_fd=directory)
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
            os.fsync(fd)
            metadata = os.fstat(fd)
            unsafe = not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            unsafe = unsafe or metadata.st_nlink != 1 or bool(metadata.st_mode & 0o077)
            if unsafe:
                reject("WRITE_REQUEST_INBOX_UNSAFE")
            os.link(
                temporary,
                final,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            return _read_replay(directory, final, request)
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
