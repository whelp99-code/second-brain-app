"""Dictionary contracts for deterministic Life read projections."""

from typing import NotRequired, TypedDict

from sb.life_event_wire import LifeEventDict


class Timeline(TypedDict):
    schema_version: int
    day: str
    timezone: str
    events: list[LifeEventDict]
    undated: list[LifeEventDict]
    coverage: str
    complete_day_observed: bool


class PreviousContext(TypedDict):
    event_id: str
    revision: int
    title: str
    excerpt: str
    event_status: str
    evidence_level: str
    raw_digest: str
    reason: str


class BriefCard(PreviousContext):
    previous_context: list[PreviousContext]
    changed: bool


class Followup(TypedDict):
    event_id: str
    revision: int
    title: str
    raw_digest: str
    reason: str


class BriefContent(TypedDict):
    day: str
    timezone: str
    slot: str
    cards: list[BriefCard]
    followups: list[Followup]
    facts_are_quoted_not_inferred: bool


class BriefSnapshot(BriefContent):
    input_version: str
    mode: str
    delivery_state: str
    omitted: int


class ViewFile(TypedDict):
    path: str
    content: str
    sha256: str


class ObsidianManifest(TypedDict):
    schema_version: int
    generation: str
    complete: bool
    files: list[ViewFile]
    managed_prefix: str
    cursor: str
    day: NotRequired[str]
    timezone: NotRequired[str]
    page_offset: NotRequired[int]
    total_files: NotRequired[int]
    next_cursor: NotRequired[str | None]
    page_complete: NotRequired[bool]
    snapshot_complete: NotRequired[bool]


class GapCandidate(TypedDict):
    event_id: str
    revision: int
    title: str
    question: str
    evidence_digest: str
