"""Persistent workflow envelopes and immutable evidence references."""

from typing import NotRequired, TypedDict

from sb.effect_values import JsonObject


class EvidenceRef(TypedDict):
    event_id: str
    revision: int
    raw_digest: str
    source_id: str
    policy_revision: str


class JournalRow(TypedDict):
    object_id: str
    kind: str
    revision: int
    body: JsonObject
    scopes: list[str]
    source_ids: list[str]
    evidence: list[EvidenceRef]
    recorded_at: str
    send_allowed: NotRequired[bool]
    execute_allowed: NotRequired[bool]


class RecordRef(TypedDict):
    record_id: str
    record_digest: str


class EventMutation(TypedDict):
    source_id: str
    event_id: str
    idempotency_key: str
    expected_revision: int
    payload: JsonObject


class Tombstone(TypedDict):
    event_id: str
    revision: int
    deleted_at: str


KINDS = frozenset(
    {
        "question",
        "briefing",
        "relation",
        "entity_alias",
        "prediction",
        "actual",
        "collection",
        "view_ack",
        "model_reservation",
        "delivery",
        "receipt_state",
        "import_receipt",
    }
)
