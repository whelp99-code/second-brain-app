"""Dictionary contracts for deterministic Life read projections."""

from typing import NotRequired

from typing_extensions import TypedDict

from sb.life_event_wire import LifeEventDict


class Timeline(TypedDict, closed=True):
    schema_version: int
    day: str
    timezone: str
    events: list[LifeEventDict]
    undated: list[LifeEventDict]
    coverage: str
    complete_day_observed: bool


class PreviousContext(TypedDict, closed=True):
    event_id: str
    revision: int
    title: str
    excerpt: str
    event_status: str
    evidence_level: str
    raw_digest: str
    reason: str


class BriefCard(TypedDict, closed=True):
    event_id: str
    revision: int
    title: str
    excerpt: str
    event_status: str
    evidence_level: str
    raw_digest: str
    reason: str
    previous_context: list[PreviousContext]
    changed: bool


class Followup(TypedDict, closed=True):
    event_id: str
    revision: int
    title: str
    raw_digest: str
    reason: str


class BriefContent(TypedDict, closed=True):
    day: str
    timezone: str
    slot: str
    cards: list[BriefCard]
    followups: list[Followup]
    facts_are_quoted_not_inferred: bool


class BriefSnapshot(TypedDict, closed=True):
    day: str
    timezone: str
    slot: str
    cards: list[BriefCard]
    followups: list[Followup]
    facts_are_quoted_not_inferred: bool
    input_version: str
    mode: str
    delivery_state: str
    omitted: int


class ViewFile(TypedDict, closed=True):
    path: str
    content: str
    sha256: str


class ObsidianManifest(TypedDict, closed=True):
    schema_version: int
    generation: str
    source_generation: str
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


class GapCandidate(TypedDict, closed=True):
    event_id: str
    revision: int
    title: str
    question: str
    evidence_digest: str
