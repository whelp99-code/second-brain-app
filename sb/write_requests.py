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
from sb.page_ids import git_rel
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


def _read_replay(directory: int, final: str, request: MemoryWriteRequestV1) -> MemoryWriteResultV1:
    preview = os.stat(final, dir_fd=directory, follow_symlinks=False)
    fd = os.open(
        final,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    try:
        before = os.fstat(fd)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_ENVELOPE_BYTES:
            block = os.read(fd, min(65_536, MAX_ENVELOPE_BYTES + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        existing = b"".join(chunks)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    match = re.match(rb'^\{"accepted_at":"([^"]+)"', existing)
    accepted = match.group(1).decode() if match is not None else ""
    envelope = MemoryWriteInboxEnvelopeV1(1, "pending", accepted, request)
    expected = canonical_bytes(asdict(envelope)) + b"\n"
    safe = _safe_file(preview) and _same(preview, before) and _same(before, after)
    if not safe or len(existing) > MAX_ENVELOPE_BYTES or existing != expected:
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
