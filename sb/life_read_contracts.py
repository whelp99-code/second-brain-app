"""Life recall response contracts."""

from typing import NotRequired

from typing_extensions import TypedDict

from sb.life_journal_contracts import RecordRef
from sb.life_json import LifePayload


class RecallEvidence(TypedDict, closed=True):
    event_id: str
    revision: int
    raw_digest: str


class RecallHit(TypedDict, closed=True):
    event_id: str
    revision: int
    title: str
    text: str
    event_status: str
    evidence_level: str
    historical: bool
    current_revision: int
    changed_since: bool
    occurred_start: str | None
    recorded_at: str
    change_reason: str | None
    evidence: RecallEvidence
    records: list[RecordRef]


class RecallResult(TypedDict, closed=True):
    state: str
    query: str
    as_of: str | None
    trigger: str
    why_now: str
    hits: list[RecallHit]
    backend: str
    generated_facts: bool


class TimelineQuery(TypedDict, closed=True):
    schema_version: int
    day: str
    timezone: str
    events: list[LifePayload]
    next_cursor: str | None
    complete: bool
    generation: str | None
    complete_day_observed: bool
    coverage: NotRequired[str]
    undated_query: NotRequired[bool]
    undated: NotRequired[list[LifePayload]]
    undated_next_cursor: NotRequired[str | None]
