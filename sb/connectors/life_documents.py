"""Read owner-exported mail, Kakao, and call files. Never fetches an account."""

from __future__ import annotations

import json
from collections.abc import Iterator
from email import message_from_bytes
from email.message import Message
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef

ADAPTER_ID: Final = "life-documents"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "life", "life_documents", "mail", "kakao", "calls"})
_TEXT_SUFFIXES: Final = frozenset({".eml", ".txt", ".vtt"})
_AUDIO_SUFFIXES: Final = frozenset({".m4a", ".wav", ".mp3", ".aac"})
_MAX_BYTES: Final = 10 * 1024 * 1024


class _ConnectorConfig(Protocol):
    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class LifeDocumentsAdapter:
    accepted_adapters: Final = _ADAPTERS

    def __init__(self, root: Path, source_id: str) -> None:
        self.source_id: str = source_id
        self._root: Path = root
        self._next_cursor: str = "0"

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = _cursor_map(cursor)
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
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(self._root).as_posix()
            if path.suffix.lower() in _AUDIO_SUFFIXES:
                current[rel] = "untranscribed"
                continue
            token = (
                sha256(path.read_bytes()).hexdigest()
                if path.stat().st_size <= _MAX_BYTES
                else "too-large"
            )
            current[rel] = token
            if previous.get(rel) == token:
                continue
            items.append(self._item(path, rel, token))
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _item(self, path: Path, rel: str, token: str) -> tuple[SourceRef, bytes, ItemMeta]:
        suffix = path.suffix.lower()
        ref = SourceRef(self.source_id, rel, token)
        if suffix not in _TEXT_SUFFIXES or path.stat().st_size > _MAX_BYTES:
            return ref, b"", {"relative_path": rel, "skip_reason": "unsupported-export"}
        raw = path.read_bytes()
        text = _eml_text(raw) if suffix == ".eml" else raw.decode("utf-8", errors="replace")
        return ref, text.encode(), {"relative_path": rel}


def create(config: _ConnectorConfig) -> SourceAdapter:
    for raw in config.source_roots:
        adapter = raw.get("adapter") or raw.get("type") or ""
        if adapter not in _ADAPTERS:
            continue
        root_value = raw.get("root") or ""
        source_id = raw.get("id") or ADAPTER_ID
        return LifeDocumentsAdapter(Path(root_value or "/absent-life-export"), source_id)
    return LifeDocumentsAdapter(Path("/absent-life-export"), ADAPTER_ID)


def _eml_text(payload: bytes) -> str:
    message = message_from_bytes(payload)
    parts = [_part_text(part) for part in _walk(message)]
    body = "\n".join(part for part in parts if part)
    subject = message.get("subject") or ""
    return f"{subject}\n{body}".strip()


def _walk(message: Message) -> list[Message]:
    if message.is_multipart():
        return [part for part in message.walk() if not part.is_multipart()]
    return [message]


def _part_text(part: Message) -> str:
    if part.get_content_type() not in {"text/plain", "text/html"}:
        return ""
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _cursor_map(cursor: str | None) -> dict[str, str]:
    if not cursor or cursor == "0":
        return {}
    loaded = json.loads(cursor)
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}
