"""Source adapter protocol shared by every connector module."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, TypedDict, runtime_checkable

from sb.contracts import SourceRef


class ItemMeta(TypedDict, total=False):
    """Per-item scan metadata. `skip_reason` marks items that were not ingested."""

    relative_path: str
    cursor: str
    skip_reason: str


class SourceAdapter(Protocol):
    """One source of raw items. Cursor is adapter-defined opaque state."""

    source_id: str

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        """Yield new or changed items since `cursor`."""
        ...

    def next_cursor(self) -> str:
        """Return the cursor to persist after a completed scan."""
        ...


@runtime_checkable
class AcknowledgingSourceAdapter(Protocol):
    """Optional intake cleanup, only after source rows are durably committed."""

    def acknowledge(self, committed: Sequence[SourceRef]) -> None: ...
