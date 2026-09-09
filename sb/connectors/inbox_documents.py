"""Vault inbox document intake. The only connector allowed to move files."""

from __future__ import annotations

import json
import os
import stat as stat_module
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef
from sb.parsers import (
    FormatUnsupported,
    InvalidInput,
    LimitExceeded,
    OcrRequired,
    ParseError,
    UnsupportedSuffix,
    parser_for,
)

ADAPTER_ID: Final = "inbox-documents"
DEFAULT_SOURCE_ID: Final = "inbox"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "inbox", "inbox_documents", "documents"})
MAX_INBOX_BYTES: Final = 10 * 1024 * 1024
_SKIP_DIRS: Final = frozenset({".done", ".git", ".requests"})


@dataclass(frozen=True, slots=True)
class _InboxText:
    text: str


class _ConnectorConfig(Protocol):
    """Typed view over vault root plus optional inbox source-root override."""

    @property
    def vault_root(self) -> str: ...

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class InboxDocumentsAdapter:
    """Scans `<vault>/inbox/`. `_next_cursor` mutates across `scan()` calls."""

    accepted_adapters: Final = _ADAPTERS

    def __init__(self, root: Path, source_id: str) -> None:
        self.source_id: str = source_id
        self._root: Path = root
        self._next_cursor: str = "0"
        self._scanned: dict[str, tuple[Path, str]] = {}

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        self._scanned.clear()
        previous = _token_map(cursor)
        current: dict[str, str] = {}
        if not self._root.exists() or not self._root.is_dir() or self._root.is_symlink():
            self._next_cursor = "0"
            yield (
                SourceRef(self.source_id, "", "absent-root"),
                b"",
                {"relative_path": "", "skip_reason": "absent-root"},
            )
            return
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        for path, rel in _inbox_files(self._root):
            outcome = self._ingest(path, rel, previous.get(rel))
            current[rel] = outcome[0]
            if outcome[1] is not None:
                items.append(outcome[1])
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def acknowledge(self, committed: Sequence[SourceRef]) -> None:
        """Move only the exact scanned versions whose CAS and ledger commits succeeded."""
        versions = {(ref.source_uri, ref.source_version) for ref in committed
                    if ref.source_id == self.source_id}
        for rel, (path, token) in self._scanned.items():
            if (rel, token) not in versions or path.is_symlink() or not path.is_file():
                continue
            try:
                metadata = path.stat()
                body = _read_regular(path, metadata)
            except OSError:
                continue
            observed = f"{metadata.st_mtime_ns}:{metadata.st_size}:{sha256(body).hexdigest()}"
            if observed == token:
                _move_done(self._root, path, rel)

    def _ingest(
        self, path: Path, rel: str, previous: str | None
    ) -> tuple[str, tuple[SourceRef, bytes, ItemMeta] | None]:
        if path.is_symlink():
            return self._resume_skip(rel, "symlink", previous)
        try:
            _ = path.resolve().relative_to(self._root.resolve())
        except ValueError:
            return self._resume_skip(rel, "outside-root", previous)
        try:
            stat = path.stat()
        except OSError:
            return self._resume_skip(rel, "unreadable", previous)
        if stat.st_size > MAX_INBOX_BYTES:
            token = f"{stat.st_mtime_ns}:{stat.st_size}:size-limit"
            if previous == token:
                return token, None
            return token, _skip(self.source_id, rel, "size-limit")
        try:
            body = _read_regular(path, stat)
        except OSError:
            return self._resume_skip(rel, "unreadable", previous)
        token = f"{stat.st_mtime_ns}:{stat.st_size}:{sha256(body).hexdigest()}"
        self._scanned[rel] = (path, token)
        if previous == token:
            return token, None
        parsed = _parse_body(path.suffix, body)
        if isinstance(parsed, _InboxText):
            meta: ItemMeta = {"relative_path": rel, "cursor": token}
            return token, (SourceRef(self.source_id, rel, token), parsed.text.encode(), meta)
        return token, _skip(self.source_id, rel, parsed)

    def _resume_skip(
        self, rel: str, reason: str, previous: str | None
    ) -> tuple[str, tuple[SourceRef, bytes, ItemMeta] | None]:
        if previous == reason:
            return reason, None
        return reason, _skip(self.source_id, rel, reason)


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the inbox adapter from an explicit root or `<vault>/inbox`."""
    source_id, root = _configured_root(config)
    return InboxDocumentsAdapter(root=root, source_id=source_id)


def _configured_root(config: _ConnectorConfig) -> tuple[str, Path]:
    for raw in config.source_roots:
        adapter = raw.get("adapter") or raw.get("type") or ""
        if adapter not in _ADAPTERS:
            continue
        source_id = raw.get("id") or DEFAULT_SOURCE_ID
        root_value = raw.get("root")
        if root_value:
            return source_id, Path(root_value)
        return source_id, Path(config.vault_root) / "inbox"
    return DEFAULT_SOURCE_ID, Path(config.vault_root) / "inbox"


class _Loads(Protocol):
    def __call__(
        self, s: bytes, *, object_pairs_hook: Callable[[list[tuple[str, JVal]]], dict[str, JVal]]
    ) -> JVal: ...


def _loads() -> _Loads:
    fn: _Loads | None = getattr(json, "loads", None)
    assert fn is not None
    return fn


def _pairs(pairs: list[tuple[str, JVal]]) -> dict[str, JVal]:
    return dict(pairs)


def _obj(raw: bytes) -> dict[str, JVal] | None:
    try:
        loaded = _loads()(raw, object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _token_map(cursor: str | None) -> dict[str, str]:
    if cursor is None or cursor in {"", "0"}:
        return {}
    parsed = _obj(cursor.encode())
    if parsed is None:
        return {}
    out: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(value, str) and key and value:
            out[key] = value
    return out


def _inbox_files(root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if name not in _SKIP_DIRS and not (Path(dirpath) / name).is_symlink()
        ]
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            found.append((path, rel))
    return found


def _parse_body(suffix: str, body: bytes) -> _InboxText | str:
    try:
        return _InboxText(parser_for(suffix)(body))
    except UnsupportedSuffix:
        return "unsupported-suffix"
    except InvalidInput as exc:
        return exc.reason
    except LimitExceeded:
        return "size-limit"
    except FormatUnsupported:
        return "unsupported-format"
    except OcrRequired:
        return "ocr-required"
    except ParseError as exc:
        return str(exc)


def _move_done(root: Path, _path: Path, rel: str) -> None:
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or any(part in {".", ".."} for part in parts):
        return
    descriptors: list[int] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        base = os.open(root, flags)
        descriptors.append(base)
        source = base
        for part in parts[:-1]:
            source = os.open(part, flags, dir_fd=source)
            descriptors.append(source)
        destination = base
        for part in (".done", *parts[:-1]):
            try:
                os.mkdir(part, mode=0o700, dir_fd=destination)
            except FileExistsError:
                pass
            destination = os.open(part, flags, dir_fd=destination)
            descriptors.append(destination)
        os.replace(parts[-1], parts[-1], src_dir_fd=source, dst_dir_fd=destination)
    except OSError:
        return
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _read_regular(path: Path, expected: os.stat_result) -> bytes:
    """Bound reads and reject special files or replacement during the read."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        def identity(info: os.stat_result) -> tuple[int, ...]:
            return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns)
        if not stat_module.S_ISREG(before.st_mode) or identity(before) != identity(expected):
            raise OSError("inbox file changed or is not regular")
        with os.fdopen(os.dup(fd), "rb") as stream:
            body = stream.read(MAX_INBOX_BYTES + 1)
        if (len(body) > MAX_INBOX_BYTES or len(body) != before.st_size
            or identity(before) != identity(os.fstat(fd))
            or identity(before) != identity(path.lstat())):
            raise OSError("inbox file changed during read")
        return body
    finally:
        os.close(fd)


def _skip(source_id: str, rel: str, reason: str) -> tuple[SourceRef, bytes, ItemMeta]:
    return SourceRef(source_id, rel, reason), b"", {"relative_path": rel, "skip_reason": reason}
