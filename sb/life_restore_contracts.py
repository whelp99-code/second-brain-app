"""Current Life state captured for restoration, including raw page bytes."""

from typing import NotRequired

from typing_extensions import TypedDict

from sb.store.life_rows import Cell


class RestoreSnapshot(TypedDict):
    tables: dict[str, list[list[Cell]]]
    blobs: dict[str, bytes]
    blocked: list[str]
    pages: dict[str, bytes]
    source_rows: list[list[Cell]]
    source_access: list[list[Cell]]
    page_access: list[list[Cell]]
    knowledge: list[list[Cell]]
    cursors: list[list[Cell]]
    captured_at: str


class RestoreResult(TypedDict, closed=True):
    life_preserved: bool
    events: NotRequired[int]
    tombstones: NotRequired[int]
    latest_capture: NotRequired[str]
    physical_erasure_complete: NotRequired[bool]
