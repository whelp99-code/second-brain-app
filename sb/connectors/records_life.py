"""L2 read-only life export source: raw bytes only, no model/normalize/Vault.

The explicit sb life ingest pipeline selects this adapter and normalizes the
export under the operator source policy. It never fetches an account.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.fs_safety import (
    SafeSourceFilesystem,
    SafeSourceFilesystemError,
    SourceFilesystemLimits,
)
from sb.contracts import SourceRef
from sb.life_json import decode_json

ADAPTER_ID: Final = "life-records"
ADAPTERS = frozenset({ADAPTER_ID, "life-events"})


class _Config(Protocol):
    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class LifeRecordsAdapter:
    accepted_adapters: frozenset[str] = ADAPTERS
    supports_life_events: bool = True

    def __init__(self, root: Path, source_id: str, format: str, timezone: str):
        self.root: Path = root
        self.source_id: str = source_id
        self.life_format: str = format
        self.life_timezone: str = timezone
        self._next: str = "0"

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        if not self.root.exists():
            yield SourceRef(self.source_id, "", "absent-root"), b"", {"skip_reason": "absent-root"}
            self._next = cursor or "0"
            return
        try:
            previous = decode_json(cursor) if cursor and cursor != "0" else {}
            if not isinstance(previous, dict) or any(
                not isinstance(v, str) for v in previous.values()
            ):
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            yield (
                SourceRef(self.source_id, "", "bad-cursor"),
                b"",
                {"skip_reason": "invalid-cursor"},
            )
            self._next = cursor or "0"
            return
        fs = SafeSourceFilesystem(
            [self.root],
            SourceFilesystemLimits(
                max_entries=2000,
                max_files=500,
                max_file_bytes=10 * 1024 * 1024,
                max_total_bytes=64 * 1024 * 1024,
            ),
        )
        try:
            scan = fs.scan(self.root, reject_denied=False, reject_unsafe=False)
        except SafeSourceFilesystemError:
            yield (
                SourceRef(self.source_id, "", "source-unavailable"),
                b"",
                {"skip_reason": "source-unavailable"},
            )
            self._next = cursor or "0"
            return
        current: dict[str, str] = {}
        for skipped in scan.skipped:
            yield (
                SourceRef(self.source_id, skipped.relative_path, "quarantined"),
                b"",
                {"relative_path": skipped.relative_path, "skip_reason": skipped.reason},
            )
        for entry in scan.files:
            relative = entry.relative_path
            try:
                raw, _stat = fs.read_path(self.root, relative)
            except SafeSourceFilesystemError:
                yield (
                    SourceRef(self.source_id, relative, "read-failed"),
                    b"",
                    {"relative_path": relative, "skip_reason": "source-unavailable"},
                )
                continue
            digest = sha256(raw).hexdigest()
            current[relative] = digest
            if previous.get(relative) == digest:
                continue
            yield SourceRef(self.source_id, relative, digest), raw, {"relative_path": relative}
        self._next = json.dumps(current, sort_keys=True, separators=(",", ":"))

    def next_cursor(self) -> str:
        return self._next


def create(config: _Config) -> SourceAdapter:
    for row in config.source_roots:
        if (row.get("adapter") or row.get("type")) in ADAPTERS:
            return LifeRecordsAdapter(
                Path(row.get("root") or "/absent-life-export"),
                row.get("id") or ADAPTER_ID,
                row.get("format") or "life-json",
                row.get("timezone") or "Asia/Seoul",
            )
    return LifeRecordsAdapter(Path("/absent-life-export"), ADAPTER_ID, "life-json", "Asia/Seoul")
