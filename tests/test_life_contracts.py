"""SB2 P01: strict event/time contracts; all data is synthetic."""

import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import TypedDict, Unpack

import pytest

from sb.effect_values import JsonObject, JsonValue
from sb.life_contracts import LifeInputError, SourcePolicyV1
from sb.life_values import canonical_bytes, day_window, parse_event

NOW = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)


class PolicyChanges(TypedDict, total=False):
    source_id: str
    scopes: tuple[str, ...]
    enabled: bool
    allowed_types: tuple[str, ...]
    sensitivity: str
    external_processing: str
    retention_days: int
    policy_revision: str


def policy(**changes: Unpack[PolicyChanges]) -> SourcePolicyV1:
    return replace(
        SourcePolicyV1(
            source_id="test-notes",
            scopes=("owner:test",),
            enabled=True,
            allowed_types=("note_saved", "calendar_event", "health_sample"),
        ),
        **changes,
    )


def payload(**changes: JsonValue) -> JsonObject:
    return {
        "source_item_id": "item-1",
        "source_version": "v1",
        "event_type": "note_saved",
        "title": "회의 기록",
        "body": "실제 메모",
        "occurred_start": "2026-09-26T09:00:00+09:00",
        "timezone": "Asia/Seoul",
        "time_precision": "minute",
        **changes,
    }


def test_event_has_stable_identity_and_separate_recording_time():
    first = parse_event(payload(), policy(), recorded_at=NOW)
    second = parse_event(
        payload(body="정정", source_version="v2"),
        policy(),
        recorded_at=NOW + timedelta(hours=1),
        revision=2,
    )
    assert first.event_id == second.event_id
    assert first.revision == 1 and second.revision == 2
    assert first.occurred_start == "2026-09-26T00:00:00+00:00"
    assert first.recorded_at == "2026-09-26T03:00:00+00:00"
    assert first.raw_digest != second.raw_digest
    assert first.scopes == ("owner:test",)
    with pytest.raises(FrozenInstanceError):
        first.title = "overwrite"


def test_different_occurrences_are_not_deduplicated_by_body():
    first = parse_event(payload(), policy(), recorded_at=NOW)
    second = parse_event(payload(source_item_id="item-2"), policy(), recorded_at=NOW)
    assert first.event_id != second.event_id


def test_source_and_scope_are_operator_derived():
    for field, value in (
        ("source_id", "other"),
        ("scopes", ["other"]),
        ("sensitivity", "public"),
        ("external_processing", "allowed"),
        ("recorded_at", "2020-01-01T00:00:00Z"),
        ("revision", 9),
    ):
        with pytest.raises(LifeInputError):
            parse_event(payload(**{field: value}), policy(), recorded_at=NOW)


def test_disabled_or_unconfigured_types_rejected():
    with pytest.raises(LifeInputError):
        parse_event(payload(), policy(enabled=False), recorded_at=NOW)
    with pytest.raises(LifeInputError):
        parse_event(payload(event_type="location_point"), policy(), recorded_at=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_item_id": ""},
        {"source_version": ""},
        {"title": ""},
        {"title": "bad\x00title"},
        {"body": 42},
        {"unknown": "reject"},
        {"event_status": "done"},
        {"evidence_level": "certain"},
        {"review_state": "approved"},
        {"timezone": "Mars/Olympus"},
        {"occurred_start": "2026-09-26T09:00:00"},
        {"occurred_end": "2026-09-25T00:00:00Z"},
        {"valid_from": "2026-09-26T00:00:00Z", "valid_until": "2026-09-25T00:00:00Z"},
        {"value": True},
        {"value": math.nan},
        {"value": math.inf},
        {"value": 0, "value_status": "unavailable"},
        {"value": None, "value_status": "observed"},
        {"confidence": True},
        {"confidence": 1.01},
        {"confidence": -0.01},
    ],
)
def test_invalid_values_are_not_silently_normalized(changes):
    with pytest.raises(LifeInputError):
        parse_event(payload(**changes), policy(), recorded_at=NOW)


def test_numeric_zero_is_not_missing():
    zero = parse_event(
        payload(value=0, value_status="observed", unit="count"), policy(), recorded_at=NOW
    )
    missing = parse_event(
        payload(value=None, value_status="unavailable"), policy(), recorded_at=NOW
    )
    assert zero.value == 0 and missing.value is None
    assert missing.value_status == "unavailable"


def test_unknown_occurrence_does_not_become_recorded_time():
    event = parse_event(
        payload(occurred_start=None, time_precision="unknown"), policy(), recorded_at=NOW
    )
    assert event.occurred_start is None
    assert event.recorded_at


def test_calendar_stays_planned_even_if_start_is_in_past():
    event = parse_event(
        payload(event_type="calendar_event", event_status="planned"), policy(), recorded_at=NOW
    )
    assert event.event_status == "planned"
    cancelled = parse_event(
        payload(event_type="calendar_event", event_status="cancelled"), policy(), recorded_at=NOW
    )
    assert cancelled.event_status == "cancelled"


def test_explicit_health_policy_cannot_relax_local_only():
    with pytest.raises(LifeInputError):
        policy(sensitivity="restricted", external_processing="explicitly_allowed")


@pytest.mark.parametrize(
    "day,zone,hours",
    [
        ("2026-09-26", "Asia/Seoul", 24),
        ("2026-03-08", "America/New_York", 23),
        ("2026-11-01", "America/New_York", 25),
    ],
)
def test_day_window_respects_zone_and_dst(day, zone, hours):
    start, end = day_window(day, zone)
    assert (end - start).total_seconds() == hours * 3600
    assert start.tzinfo == UTC and end.tzinfo == UTC


def test_kst_midnight_window():
    start, end = day_window("2026-09-26", "Asia/Seoul")
    assert start.isoformat() == "2026-09-25T15:00:00+00:00"
    assert end.isoformat() == "2026-09-26T15:00:00+00:00"


def test_canonical_input_does_not_depend_on_dictionary_order():
    assert canonical_bytes({"b": 1, "a": "한글"}) == canonical_bytes({"a": "한글", "b": 1})
    with pytest.raises(LifeInputError):
        canonical_bytes({"bad": math.nan})
