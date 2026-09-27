"""P01 contracts: deterministic, synthetic, no real device or external model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from sb.life_config import parse_settings
from sb.life_contracts import (
    LifeError,
    LifeEventV1,
    SourcePolicyV1,
    day_window,
    event_input,
    instant,
    parse_event,
    stable_event_id,
    strict_json,
)

NOW = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
POLICY = SourcePolicyV1("phone", "personal", enabled=True)


def payload(**changes):
    return {
        "source_id": "phone",
        "source_item_id": "capture:1",
        "source_version": "1",
        "title": "고객 미팅",
        "body": "일정만 등록됨",
        "event_type": "calendar_event",
        "event_status": "planned",
        "occurred_start": "2026-09-26T10:00:00+09:00",
        **changes,
    }


def settings_raw():
    return {
        "life": {
            "features": {
                "life_events": True,
                "life_timeline": True,
                "obsidian_view": True,
                "life_briefing": True,
                "gap_questions": True,
                "contextual_recall": True,
                "prediction": True,
            },
            "sources": [{"id": "phone", "scope": "personal", "enabled": True}],
            "clients": [
                {
                    "id": "mobile",
                    "token_env": "SB_LIFE_TEST_DEVICE",
                    "scopes": ["personal"],
                    "source_ids": ["phone"],
                    "operations": ["read", "capture", "correct", "forget", "run", "answer", "ack"],
                }
            ],
        }
    }


def test_roundtrip_and_frozen_contract():
    event = parse_event(payload(), POLICY, NOW)
    assert event.event_id == stable_event_id("phone", "capture:1")
    assert event.event_status == "planned"
    assert event.evidence_level == "observed"
    assert event.review_state == "unreviewed"
    assert event.occurred_start == "2026-09-26T01:00:00.000000Z"
    assert event.recorded_at == "2026-09-26T03:00:00.000000Z"
    assert LifeEventV1.from_dict(event.as_dict()) == event
    assert parse_event(event_input(event), POLICY, NOW).event_id == event.event_id
    with pytest.raises(FrozenInstanceError):
        event.title = "overwrite"


def test_repeat_occurrence_is_distinct_and_unknown_time_remains_unknown():
    a = parse_event(payload(source_item_id="occurrence:2026-09-25"), POLICY, NOW)
    b = parse_event(payload(source_item_id="occurrence:2026-09-26"), POLICY, NOW)
    assert a.event_id != b.event_id
    assert a.title == b.title
    missing = parse_event(payload(occurred_start=None), POLICY, NOW)
    assert missing.occurred_start is None and missing.time_precision == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "other-project"},
        {"revision": 99},
        {"recorded_at": "2020-01-01T00:00:00Z"},
        {"raw_hash": "0" * 64},
        {"event_status": "finished"},
        {"confidence": True},
        {"confidence": float("nan")},
        {"value": float("inf")},
        {"value": True},
        {"value": None, "value_status": "observed"},
        {"value": 0, "value_status": "missing"},
        {"event_id": "invented"},
        {"occurred_start": "2026-09-26T01:00:00"},
        {"occurred_end": "2026-09-25T01:00:00Z"},
        {"occurred_start": None, "occurred_end": "2026-09-26T01:00:00Z"},
        {"occurred_start": None, "time_precision": "exact"},
        {"timezone": "../UTC"},
        {"sensitivity": "public"},
        {"external_processing": "explicitly_allowed"},
        {"valid_from": "2026-09-26T00:00:00Z", "valid_until": "2026-09-25T00:00:00Z"},
        {"entity_refs": [{"entity_id": "person:1", "kind": "person", "name": "A", "admin": True}]},
    ],
)
def test_invalid_contract_rejected(changes):
    with pytest.raises(LifeError):
        parse_event(payload(**changes), POLICY, NOW)


def test_values_missing_and_zero_are_different():
    zero = parse_event(payload(value=0, unit="minute"), POLICY, NOW)
    missing = parse_event(payload(value=None, value_status="unavailable"), POLICY, NOW)
    assert zero.value == 0 and zero.value_status == "observed"
    assert missing.value is None and missing.value_status == "unavailable"


def test_entities_are_preserved_without_name_merging():
    event = parse_event(
        payload(
            entity_refs=[
                {"entity_id": "person:1", "kind": "person", "name": "김민수"},
                {"entity_id": "person:2", "kind": "person", "name": "김민수"},
            ]
        ),
        POLICY,
        NOW,
    )
    assert len(event.entity_refs) == 2
    assert parse_event(event_input(event), POLICY, NOW).entity_refs == event.entity_refs


def test_kst_and_dst_windows():
    start, end = day_window("2026-09-26", "Asia/Seoul")
    assert start.isoformat() == "2026-09-25T15:00:00+00:00"
    assert (end - start).total_seconds() == 86400
    start, end = day_window("2026-03-08", "America/New_York")
    assert (end - start).total_seconds() == 23 * 3600
    start, end = day_window("2026-11-01", "America/New_York")
    assert (end - start).total_seconds() == 25 * 3600


def test_sensitive_samples_require_restricted_local_policy():
    with pytest.raises(LifeError, match="LIFE_SENSITIVE_INPUT_POLICY"):
        parse_event(payload(event_type="health_sample"), POLICY, NOW)
    policy = replace(POLICY, sensitivity="restricted")
    assert parse_event(payload(event_type="health_sample", value=0), policy, NOW).value == 0


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "{bad"])
def test_strict_json_rejects_non_json(raw):
    with pytest.raises(LifeError):
        strict_json(raw)


def test_config_default_off_and_source_opt_in():
    assert not parse_settings({}).enabled("life_events")
    settings = parse_settings(settings_raw())
    assert settings.enabled("obsidian_view")
    assert settings.clients[0].principal(NOW).permits("capture", settings.source("phone"))
    with pytest.raises(LifeError, match="LIFE_SOURCE_DISABLED"):
        parse_event(payload(), replace(POLICY, enabled=False), NOW)


@pytest.mark.parametrize(
    "section",
    [
        {"features": {"life_events": "true"}},
        {"features": {"obsidian_view": True}},
        {"features": {"life_events": True}},
        {"sources": [{"id": "phone", "scope": "personal", "enabled": "yes"}]},
        {"question_budget": True},
        {"quiet_end": 24},
        {"max_batch": 101},
        {"unknown": True},
    ],
)
def test_bad_configuration_fails_closed(section):
    with pytest.raises(LifeError):
        parse_settings({"life": section})


def test_client_expiry_and_scope_are_not_payload_authority():
    raw = settings_raw()
    raw["life"]["clients"][0]["expires_at"] = "2026-09-25T00:00:00Z"
    settings = parse_settings(raw)
    with pytest.raises(LifeError, match="LIFE_SESSION_EXPIRED"):
        settings.clients[0].principal(NOW)
    raw["life"]["clients"][0]["scopes"] = ["other"]
    with pytest.raises(LifeError):
        parse_settings(raw)
    assert instant("2026-09-26T12:00:00+09:00") == NOW
