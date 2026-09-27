"""Exact dictionary shapes emitted by the frozen Life event contracts."""

from typing_extensions import TypedDict


class EntityRefDict(TypedDict, closed=True):
    entity_id: str
    kind: str
    label: str


class AttachmentRefDict(TypedDict, closed=True):
    name: str
    mime: str
    size: int
    sha256: str


class LifeEventDict(TypedDict, closed=True):
    schema_version: int
    event_id: str
    revision: int
    source_id: str
    source_item_id: str
    source_version: str
    event_type: str
    title: str
    body: str
    event_status: str
    evidence_level: str
    review_state: str
    occurred_start: str | None
    occurred_end: str | None
    observed_at: str | None
    recorded_at: str
    timezone: str
    time_precision: str
    valid_from: str | None
    valid_until: str | None
    entities: list[EntityRefDict]
    scopes: list[str]
    sensitivity: str
    external_processing: str
    retention_days: int
    raw_digest: str
    value: float | int | None
    value_status: str
    unit: str | None
    confidence: float | None
    change_reason: str | None
    policy_revision: str
    attachments: tuple[AttachmentRefDict, ...]


class LifeReceiptDict(TypedDict, closed=True):
    receipt_id: str
    event_id: str
    revision: int
    accepted_at: str
    replayed: bool
    state: str
