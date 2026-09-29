"""SB2 P01: strict event/time contracts; all data is synthetic."""

import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import TypedDict, Unpack

import pytest

from sb.effect_values import JsonObject, JsonValue
from sb.life_contracts import LifeInputError, SourcePolicyV1, allowed_transition
from sb.life_values import canonical_bytes, day_window, in_day_window, instant, parse_event

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


def test_event_has_stable_identity_and_separate_recording_time() -> None:
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
        first.__setattr__("title", "overwrite")


def test_different_occurrences_are_not_deduplicated_by_body() -> None:
    first = parse_event(payload(), policy(), recorded_at=NOW)
    second = parse_event(payload(source_item_id="item-2"), policy(), recorded_at=NOW)
    assert first.event_id != second.event_id


def test_source_and_scope_are_operator_derived() -> None:
    fields: tuple[tuple[str, JsonValue], ...] = (
        ("source_id", "other"),
        ("scopes", ["other"]),
        ("sensitivity", "public"),
        ("external_processing", "allowed"),
        ("recorded_at", "2020-01-01T00:00:00Z"),
        ("revision", 9),
    )
    for field, value in fields:
        with pytest.raises(LifeInputError):
            _ = parse_event(payload(**{field: value}), policy(), recorded_at=NOW)


def test_disabled_or_unconfigured_types_rejected() -> None:
    with pytest.raises(LifeInputError):
        _ = parse_event(payload(), policy(enabled=False), recorded_at=NOW)
    with pytest.raises(LifeInputError):
        _ = parse_event(payload(event_type="location_point"), policy(), recorded_at=NOW)


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
def test_invalid_values_are_not_silently_normalized(changes: JsonObject) -> None:
    with pytest.raises(LifeInputError):
        _ = parse_event(payload(**changes), policy(), recorded_at=NOW)


def test_numeric_zero_is_not_missing() -> None:
    zero = parse_event(
        payload(value=0, value_status="observed", unit="count"), policy(), recorded_at=NOW
    )
    missing = parse_event(
        payload(value=None, value_status="unavailable"), policy(), recorded_at=NOW
    )
    assert zero.value == 0 and missing.value is None
    assert missing.value_status == "unavailable"


def test_unknown_occurrence_does_not_become_recorded_time() -> None:
    event = parse_event(
        payload(occurred_start=None, time_precision="unknown"), policy(), recorded_at=NOW
    )
    assert event.occurred_start is None
    assert event.recorded_at


def test_calendar_stays_planned_even_if_start_is_in_past() -> None:
    event = parse_event(
        payload(event_type="calendar_event", event_status="planned"), policy(), recorded_at=NOW
    )
    assert event.event_status == "planned"
    cancelled = parse_event(
        payload(event_type="calendar_event", event_status="cancelled"), policy(), recorded_at=NOW
    )
    assert cancelled.event_status == "cancelled"


def test_explicit_health_policy_cannot_relax_local_only() -> None:
    with pytest.raises(LifeInputError):
        _ = policy(sensitivity="restricted", external_processing="explicitly_allowed")


@pytest.mark.parametrize(
    "day,zone,hours",
    [
        ("2026-09-26", "Asia/Seoul", 24),
        ("2026-03-08", "America/New_York", 23),
        ("2026-11-01", "America/New_York", 25),
    ],
)
def test_day_window_respects_zone_and_dst(day: str, zone: str, hours: int) -> None:
    start, end = day_window(day, zone)
    assert (end - start).total_seconds() == hours * 3600
    assert start.tzinfo == UTC and end.tzinfo == UTC


def test_kst_midnight_window() -> None:
    start, end = day_window("2026-09-26", "Asia/Seoul")
    assert start.isoformat() == "2026-09-25T15:00:00+00:00"
    assert end.isoformat() == "2026-09-26T15:00:00+00:00"


def test_canonical_input_does_not_depend_on_dictionary_order() -> None:
    assert canonical_bytes({"b": 1, "a": "한글"}) == canonical_bytes({"a": "한글", "b": 1})
    with pytest.raises(LifeInputError):
        _ = canonical_bytes({"bad": math.nan})


def test_transition_planned_to_occurred_requires_non_inferred_evidence():
    assert allowed_transition("planned", "occurred", evidence_level="observed")
    assert allowed_transition("planned", "occurred", evidence_level="user_asserted")
    assert not allowed_transition("planned", "occurred", evidence_level="inferred")
    event = parse_event(
        payload(
            event_type="calendar_event",
            event_status="planned",
            evidence_level="inferred",
            observed_at="2026-09-26T10:00:00+09:00",
        ),
        policy(),
        recorded_at=NOW,
    )
    assert event.event_status == "planned"
    assert event.evidence_level == "inferred"
    assert event.observed_at == "2026-09-26T01:00:00+00:00"


def test_transition_cancelled_to_occurred_requires_user_assertion():
    assert not allowed_transition("cancelled", "occurred", evidence_level="observed")
    assert not allowed_transition("cancelled", "occurred", evidence_level="inferred")
    assert allowed_transition("cancelled", "occurred", evidence_level="user_asserted")
    assert allowed_transition("cancelled", "cancelled", evidence_level="observed")


def test_dst_fold_and_gap_instants_are_preserved_not_shifted():
    fold_first = "2026-11-01T01:30:00-04:00"
    fold_second = "2026-11-01T01:30:00-05:00"
    gap = "2026-03-08T02:30:00-04:00"
    assert instant(fold_first).isoformat() == "2026-11-01T05:30:00+00:00"
    assert instant(fold_second).isoformat() == "2026-11-01T06:30:00+00:00"
    assert instant(gap).isoformat() == "2026-03-08T06:30:00+00:00"
    assert instant(fold_first) != instant(fold_second)
    for raw, expected in (
        (fold_first, "2026-11-01T05:30:00+00:00"),
        (fold_second, "2026-11-01T06:30:00+00:00"),
        (gap, "2026-03-08T06:30:00+00:00"),
    ):
        event = parse_event(
            payload(occurred_start=raw, timezone="America/New_York", time_precision="minute"),
            policy(),
            recorded_at=NOW,
        )
        assert event.occurred_start == expected
        assert event.timezone == "America/New_York"


def test_delayed_upload_keeps_occurred_vs_recorded_separate():
    recorded = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    event = parse_event(
        payload(
            event_type="calendar_event",
            event_status="planned",
            occurred_start="2026-09-26T10:00:00+09:00",
            observed_at="2026-09-28T09:30:00+09:00",
            time_precision="minute",
        ),
        policy(),
        recorded_at=recorded,
    )
    assert event.occurred_start == "2026-09-26T01:00:00+00:00"
    assert event.recorded_at == "2026-09-28T01:00:00+00:00"
    assert event.observed_at == "2026-09-28T00:30:00+00:00"
    assert event.event_status == "planned"
    assert event.occurred_start != event.recorded_at
    assert event.observed_at != event.occurred_start


def test_travel_timezone_day_window_is_half_open():
    start, end = day_window("2026-06-15", "Europe/Paris")
    assert in_day_window(start, "2026-06-15", "Europe/Paris")
    assert not in_day_window(end, "2026-06-15", "Europe/Paris")
    assert in_day_window(end, "2026-06-16", "Europe/Paris")
    previous_start, previous_end = day_window("2026-06-14", "Europe/Paris")
    assert previous_end == start
    assert not in_day_window(start, "2026-06-14", "Europe/Paris")
    assert (start, end) != day_window("2026-06-15", "Asia/Seoul")
    assert start.isoformat() == "2026-06-14T22:00:00+00:00"
    assert end.isoformat() == "2026-06-15T22:00:00+00:00"
    assert previous_start < start < end
