"""Descriptor-safe pending-request publication shared by V1/V3/V4 admission."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sb.effect_values import parse_instant
from sb.task30_barriers import BoundBarrierEmitter
from sb.write_request_values import MAX_ENVELOPE_BYTES, parse_remember_envelope


class StableRequestError(ValueError):
    pass


def safe_request_file(metadata: os.stat_result, links: int = 1) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == links
    )


@dataclass(frozen=True, slots=True)
class PendingPublication:
    name: str
    payload: bytes
    emitter: BoundBarrierEmitter
    validate_recovery: Callable[[bytes, bytes], None] | None = None
    max_bytes: int = MAX_ENVELOPE_BYTES


def recover_publication(path: Path, expected: bytes, *, links: int = 1,
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


def publish_pending(directory: Path, publication: PendingPublication) -> bytes:
    def recover(path: Path, expected: bytes, *, links: int = 1) -> bytes:
        return recover_publication(path, expected, links=links,
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
