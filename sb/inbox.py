"""Collision-safe `inbox/` writes, shared by the CLI and the MCP server.

Explicit request IDs use a content-addressed final path. Unkeyed calls retain
the frozen timestamp filename contract. Publication is exclusive, and error
observation uses the same identity as publication. There is no side retry file.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, assert_never, override

from sb.config import Config
from sb.connectors.inbox_documents import InboxDocumentsAdapter
from sb.connectors.inbox_documents import create as create_inbox_adapter
from sb.parsers import ParseError, parser_for
from sb.sqlite_values import SQL_ROWS

MAX_REMEMBER_BYTES: Final = 1024 * 1024
_SLUG_RE: Final = re.compile(r"[^0-9A-Za-z가-힣]+")
_LINK_FALLBACK: Final = {errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL}
_RENAME_NOREPLACE: Final = 1
_AT_FDCWD: Final = -100

PageState = Literal["present", "absent", "unknown", "conflict"]


@dataclass(frozen=True, slots=True)
class RememberRejected(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(slots=True)
class RememberFollowupError(Exception):
    """Final page is present; a later step failed. Not NOTHING_WRITTEN."""

    relative: Path

    @override
    def __str__(self) -> str:
        return f"WRITTEN_WITH_FOLLOWUP_ERROR: {self.relative.as_posix()}"


class RememberOutcomeUnknown(Exception):
    """The final path could not be classified. Not proof the page is absent."""

    def __init__(self, relative: Path) -> None:
        self.relative = relative
        super().__init__(f"WRITE_OUTCOME_UNKNOWN: {relative.as_posix()}")


class InboxModeRestoreError(Exception):
    """Sealed inbox mode could not be restored. Do not treat the page as unwritten."""

    def __init__(self, inbox: Path, mode: int, saved: Path | None) -> None:
        self.inbox = inbox
        self.mode = mode
        self.saved = saved
        super().__init__(f"INBOX_MODE_RESTORE_FAILED: {mode:04o} {inbox}")


@dataclass(frozen=True, slots=True)
class ParsedRemember:
    data: bytes
    title: str | None


def _slug(title: str | None) -> str:
    raw = "" if title is None else title.strip()
    cleaned = _SLUG_RE.sub("-", raw).strip("-").lower()
    return (cleaned or "note")[:40]


def normalized_title(title: str | None) -> str:
    """None and surrounding whitespace are the same title. The body is not rewritten."""
    return "" if title is None else title.strip()


_REQUEST_ID_RE: Final = re.compile(r"[0-9A-Za-z_-]{1,64}")


@dataclass(slots=True)
class RememberIdentity:
    """Keep the selected collision suffix visible to post-failure observation."""

    kind: Literal["legacy", "explicit"]
    token: str
    collision: int = 0


def remember_identity(
    request_id: str | RememberIdentity | None, *, now: datetime | None = None,
) -> RememberIdentity:
    """Parse public IDs once; omitted IDs mint a fresh legacy publication."""
    match request_id:
        case RememberIdentity():
            return request_id
        case str():
            if _REQUEST_ID_RE.fullmatch(request_id) is None:
                raise RememberRejected("REMEMBER_REQUEST_ID_INVALID")
            return RememberIdentity("explicit", request_id)
        case None:
            clock = datetime.now(UTC) if now is None else now
            return RememberIdentity("legacy", clock.strftime("%Y-%m-%dT%H%M%S%f"))
        case unreachable:
            assert_never(unreachable)


def remember_digest(data: bytes, title: str | None, request_id: str) -> str:
    """sha256 of request id, normalized title, and exact body bytes.

    The runtime contract requires two identical remembers to be two pages
    (``test_mcp_contract_runtime``). A client-supplied request id is therefore
    part of the hash. The same id, title, and body are one page. A different
    title or a different id is a different page. An omitted id is not a retry.
    """
    title_bytes = normalized_title(title).encode("utf-8")
    identity = request_id.encode("ascii")
    return hashlib.sha256(
        b"sb-remember/v3\0" + identity + b"\0" + title_bytes + b"\0" + data
    ).hexdigest()


def page_filename(data: bytes, title: str | None, identity: RememberIdentity) -> str:
    """Keep legacy filenames unchanged and explicit-ID retries deterministic."""
    match identity.kind:
        case "legacy":
            suffix = f"-{identity.collision}" if identity.collision else ""
            return f"{identity.token}-{_slug(title)}{suffix}.md"
        case "explicit":
            return f"{remember_digest(data, title, identity.token)}-{_slug(title)}.md"
        case unreachable:
            assert_never(unreachable)


def parse_remember(content: str, title: str | None) -> ParsedRemember:
    """Parse one remember payload before acquiring generation resources."""
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RememberRejected("invalid utf-8") from exc
    if len(data) > MAX_REMEMBER_BYTES:
        raise RememberRejected("content exceeds 1MB")
    return ParsedRemember(data, title)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                return b"".join(chunks)
            chunks.append(block)
    finally:
        os.close(descriptor)


def observe_page(path: Path, expected: bytes) -> PageState:
    """Classify only by the final path. Never by which earlier step raised."""
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        return "unknown"
    try:
        payload = _read_file(path)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    if payload != expected:
        return "conflict"
    return "present"


def observe_remember(
    root: Path, content: str, title: str | None, request_id: RememberIdentity,
    *, config: Config | None = None,
) -> tuple[PageState, str | None]:
    """Return the final-path state and, when present, the vault-relative path."""
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        return "absent", None
    try:
        name = page_filename(data, title, request_id)
    except RememberRejected:
        return "absent", None
    dest = root / "inbox" / name
    state = observe_page(dest, data)
    if state == "absent" and request_id.kind == "explicit":
        try:
            if _consumed_remember(root.resolve(), Path("inbox") / name, data, config):
                return "present", (Path("inbox") / name).as_posix()
        except RememberOutcomeUnknown:
            return "unknown", None
    if state != "present":
        return state, None
    try:
        return state, dest.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "unknown", None


def _consumed_remember(
    root: Path, relative: Path, data: bytes, config: Config | None,
) -> bool:
    """Reconcile an exact explicit filename against ack or committed ingestion."""
    try:
        if (root / "inbox").is_symlink():
            raise OSError("unsafe inbox directory")
        done = root / "inbox" / ".done"
        if done.is_symlink():
            raise OSError("unsafe acknowledgement directory")
        archived = done / relative.name
        state = observe_page(archived, data)
        if state == "present":
            metadata = archived.stat()
            if metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
                raise OSError("unsafe acknowledged page")
            return True
        if state != "absent":
            raise OSError("unverifiable acknowledged page")
        ledger = root / ".sb" / "ledger.db"
        if ledger.parent.is_symlink() or ledger.is_symlink():
            raise OSError("unsafe ingestion ledger")
        try:
            metadata = ledger.stat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
            raise OSError("unsafe ingestion ledger")
        with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = SQL_ROWS.validate_python(connection.execute(
                "SELECT source_id,source_version,content_hash FROM source_item WHERE source_uri=?",
                (relative.name,),
            ).fetchall(), strict=True)
        if not rows:
            return False
        if config is None:
            raise ValueError("inbox source identity unavailable")
        adapter = create_inbox_adapter(config)
        if not isinstance(adapter, InboxDocumentsAdapter):
            raise TypeError("inbox adapter identity unavailable")
        if "sources" in config.raw and not any(
            row.get("id") == adapter.source_id
            and (row.get("adapter") or row.get("type")) in adapter.accepted_adapters
            for row in config.source_roots
        ):
            raise ValueError("inbox source is not selected by configuration")
        if adapter.root.resolve() != (Path(config.vault_root) / "inbox").resolve():
            raise ValueError("configured source does not consume the publication inbox")
        rows = [row for row in rows if row[0] == adapter.source_id]
        if not rows:
            raise ValueError("no ingestion evidence for configured inbox source")
        raw_hash = hashlib.sha256(data).hexdigest()
        parsed_hash = hashlib.sha256(parser_for(".md")(data).encode()).hexdigest() if rows else ""
        for _source_id, version, digest in rows:
            if not isinstance(version, str) or not isinstance(digest, str):
                raise TypeError("invalid ingestion evidence")
            parts = version.split(":")
            if (len(parts) != 3 or not parts[0].isdecimal()
                    or parts[1:] != [str(len(data)), raw_hash]
                    or digest != parsed_hash):
                raise ValueError("ingestion identity mismatch")
            raw = root / "raw" / digest[:2] / digest
            if raw.parent.parent.is_symlink() or raw.parent.is_symlink():
                raise OSError("unsafe ingested content")
            metadata = raw.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or metadata.st_nlink != 1 or hashlib.sha256(_read_file(raw)).hexdigest() != digest):
                raise OSError("unverifiable ingested content")
        return bool(rows)
    except (OSError, sqlite3.Error, TypeError, ValueError, ParseError) as exc:
        raise RememberOutcomeUnknown(relative) from exc


def _saved_page(dest: Path) -> Path | None:
    try:
        metadata = os.lstat(dest)
    except OSError:
        return None
    if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        return dest
    return None


def _restore_mode(inbox: Path, mode: int, changed: bool, saved: Path | None) -> None:
    if not changed:
        return
    try:
        inbox.chmod(mode)
    except OSError as exc:
        raise InboxModeRestoreError(inbox, mode, saved) from exc


def _rename_noreplace(src: Path, dst: Path) -> None:
    """Linux renameat2(RENAME_NOREPLACE). Does not replace an existing final name."""
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.renameat2(
        _AT_FDCWD,
        os.fsencode(src),
        _AT_FDCWD,
        os.fsencode(dst),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(dst))


def _link_noreplace(src: Path, dst: Path) -> bool:
    """Publish by exclusive link. Fall back to renameat2 only if link cannot work."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in _LINK_FALLBACK:
            raise
        _rename_noreplace(src, dst)
        return True
    return False


def _exclusive_create(dest: Path, data: bytes) -> None:
    """Create the final name once. A retry finds that name and does not add a page."""
    temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count <= 0:
                raise OSError(errno.EIO, "short write")
            written += count
        os.fsync(descriptor)
    except OSError:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    try:
        moved = _link_noreplace(temporary, dest)
    except FileExistsError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    try:
        _fsync_directory(dest.parent)
        if not moved:
            temporary.unlink()
        _fsync_directory(dest.parent)
    except OSError as exc:
        if not moved:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise RememberFollowupError(dest.relative_to(dest.parent.parent)) from exc


def _ensure_page(dest: Path, data: bytes, *, retry: bool) -> None:
    state = observe_page(dest, data)
    if state == "present":
        if retry:
            return
        raise FileExistsError(dest)
    if state == "conflict":
        if retry:
            raise RememberRejected("REMEMBER_RETRY_CONFLICT")
        raise FileExistsError(dest)
    if state == "unknown":
        raise OSError(errno.EIO, "final path unreadable")
    _exclusive_create(dest, data)


def publish_inbox(
    root: Path, note: ParsedRemember, request_id: RememberIdentity,
    *, config: Config | None = None,
) -> Path:
    """Publish one final name without replacing another note."""
    data = note.data
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
    if not inbox.is_relative_to(vault):
        raise RememberRejected("inbox escapes vault")
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / page_filename(data, note.title, request_id)
    if not dest.resolve().is_relative_to(inbox):
        raise RememberRejected("inbox escapes vault")
    relative = dest.relative_to(vault)
    if (request_id.kind == "explicit" and observe_page(dest, data) == "absent"
            and _consumed_remember(vault, relative, data, config)):
        return relative
    mode = stat.S_IMODE(os.lstat(inbox).st_mode)
    changed = False
    attempt: BaseException | None = None
    try:
        if mode & 0o200 == 0:
            inbox.chmod(mode | 0o200)
            changed = True
        try:
            while True:
                dest = inbox / page_filename(data, note.title, request_id)
                relative = dest.relative_to(vault)
                try:
                    _ensure_page(dest, data, retry=request_id.kind == "explicit")
                    break
                except FileExistsError:
                    match request_id.kind:
                        case "explicit":
                            break
                        case "legacy":
                            request_id.collision += 1
                        case unreachable:
                            assert_never(unreachable)
        except RememberRejected:
            raise
        except RememberFollowupError as exc:
            attempt = exc
        except OSError as exc:
            attempt = exc
    finally:
        _restore_mode(inbox, mode, changed, _saved_page(dest))
    state = observe_page(dest, data)
    if state == "present":
        if attempt is not None:
            raise RememberFollowupError(relative) from attempt
        return relative
    if state == "unknown":
        raise RememberOutcomeUnknown(relative) from attempt
    if state == "conflict":
        raise RememberRejected("REMEMBER_RETRY_CONFLICT")
    if attempt is not None:
        raise attempt
    raise OSError(errno.ENOENT, "remember page absent after publish")


def promote_published(root: Path, relative: Path, title: str | None) -> Path:
    """The published path is already the final name. Do not rename or rewrite it."""
    del root, title
    return relative


def write_inbox(
    root: Path, content: str, title: str | None,
    request_id: str | RememberIdentity | None = None,
    *, config: Config | None = None,
) -> Path:
    """Write UTF-8 text <=1MB to an exclusive inbox page. Never overwrites."""
    note = parse_remember(content, title)
    identity = remember_identity(request_id)
    relative = publish_inbox(root, note, identity, config=config)
    return promote_published(root, relative, title)


def discard_inbox(root: Path, relative: str) -> str:
    """Withdraw an unused inbox receipt. Refuses paths outside the vault inbox."""
    rel = Path(relative)
    if (
        rel.is_absolute()
        or ".." in rel.parts
        or len(rel.parts) != 2
        or rel.parts[0] != "inbox"
        or rel.name in {".", "..", ""}
    ):
        raise ValueError("invalid inbox path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    vault_fd = -1
    inbox_fd = -1
    file_fd = -1
    try:
        vault_fd = os.open(root, flags)
        inbox_fd = os.open("inbox", flags, dir_fd=vault_fd)
        file_fd = os.open(
            rel.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=inbox_fd,
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("invalid inbox path")
        os.unlink(rel.name, dir_fd=inbox_fd)
    except OSError as exc:
        raise ValueError("invalid inbox path") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if inbox_fd >= 0:
            os.close(inbox_fd)
        if vault_fd >= 0:
            os.close(vault_fd)
    return rel.as_posix()
