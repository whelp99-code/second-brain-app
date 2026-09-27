"""Sensor protocol/permission/deletion tests with synthetic GPS and health values."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from sb.life_config import parse_settings
from sb.life_contracts import LifeError, SourcePolicyV1, canonical, stamp, strict_json
from sb.life_sensors import health_batch, location_batch, movement_segments
from sb.life_store import read_life_store
from sb.pipeline import run_life_operation
from sb.runtime_access import read_root
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config

GPS = SourcePolicyV1("gps", "personal", "restricted", "local_only", True)
HEALTH = SourcePolicyV1(
    "health", "personal", "restricted", "local_only", True, ("steps", "sleep", "heart_rate", "hrv")
)


def point(offset=0, **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [127.0, 37.5]},
        "properties": {
            "timestamp": stamp(NOW - timedelta(hours=1) + timedelta(minutes=offset)),
            "horizontal_accuracy": 15,
            "speed": -1,
            "device_id": "synthetic-phone",
            **properties,
        },
    }


def health_payload(kind="steps", **changes):
    sample = {
        "sample_id": "sample:one",
        "start": stamp(NOW - timedelta(hours=1)),
        "end": stamp(NOW),
        "value": 0,
        "unit": "count",
        "source_bundle_id": "synthetic.health.source",
    }
    if kind == "sleep":
        sample.update(value=3600, unit="seconds", sleep_stage="asleep_core")
    elif kind == "heart_rate":
        sample.update(value=60, unit="beats/min")
    elif kind == "hrv":
        sample.update(value=40, unit="ms")
    return {
        "schema_version": 1,
        "device_id": "synthetic-phone",
        "health_type": kind,
        "previous_anchor": None,
        "anchor": "anchor:1",
        "samples": [sample],
        "deleted_ids": [],
        **changes,
    }


def sensor_config(tmp_path):
    config, root, _ = life_config(tmp_path)
    section = dict(config.raw["life"])
    section["features"] = {**section["features"], "location_capture": True, "health_capture": True}
    section["sources"] = [
        *section["sources"],
        {"id": "gps", "scope": "personal", "sensitivity": "restricted", "enabled": True},
        {
            "id": "health",
            "scope": "personal",
            "sensitivity": "restricted",
            "enabled": True,
            "health_types": ["steps", "sleep", "heart_rate", "hrv"],
        },
    ]
    config = replace(config, raw={**config.raw, "life": section})
    return config, root, parse_settings(config.raw).owner()


def ingest(config, principal, kind, payload):
    return run_life_operation(
        config,
        "sensor_" + kind,
        {"source_id": "gps" if kind == "location" else "health", "payload": payload},
        principal,
        now=NOW,
    )


def test_location_point_preserves_unknown_speed_and_deduplicates_telemetry():
    a = location_batch({"locations": [point()]}, GPS, NOW)
    b = location_batch({"locations": [point(locations_in_payload=99, battery_level=0.5)]}, GPS, NOW)
    assert a == b
    normalized = strict_json(a[0]["body"])
    assert normalized["speed_mps"] is None and normalized["latitude"] == 37.5
    assert a[0]["sensitivity"] == "restricted" and a[0]["external_processing"] == "local_only"


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["geometry"].update(coordinates=[181, 37]),
        lambda p: p["geometry"].update(coordinates=[127, 91]),
        lambda p: p["geometry"].update(coordinates=[True, 37]),
        lambda p: p["geometry"].update(type="LineString"),
        lambda p: p["properties"].update(timestamp="2026-09-26T03:00:00"),
        lambda p: p["properties"].update(timestamp=stamp(NOW + timedelta(seconds=1))),
        lambda p: p["properties"].update(horizontal_accuracy=float("nan")),
    ],
)
def test_invalid_location_batches_rejected(change):
    feature = point()
    change(feature)
    with pytest.raises(LifeError):
        location_batch({"locations": [feature]}, GPS, NOW)


def test_health_types_require_separate_opt_in_and_exact_units():
    with pytest.raises(LifeError, match="LIFE_HEALTH_TYPE_NOT_ENABLED"):
        health_batch(health_payload("hrv"), HEALTH, NOW, ("steps",))
    wrong = health_payload()
    wrong["samples"][0]["unit"] = "seconds"
    with pytest.raises(LifeError, match="LIFE_HEALTH_UNIT_INVALID"):
        health_batch(wrong, HEALTH, NOW, HEALTH.health_types)
    for kind in HEALTH.health_types:
        cursor, events, deleted = health_batch(
            health_payload(kind), HEALTH, NOW, HEALTH.health_types
        )
        assert len(events) == 1 and deleted == () and cursor["anchor"] == "anchor:1"


def test_health_zero_and_unavailable_remain_distinct():
    _, zero, _ = health_batch(health_payload(), HEALTH, NOW, HEALTH.health_types)
    missing = health_payload()
    missing["samples"][0]["value"] = None
    _, unavailable, _ = health_batch(missing, HEALTH, NOW, HEALTH.health_types)
    assert zero[0]["value"] == 0 and zero[0]["value_status"] == "observed"
    assert unavailable[0]["value"] is None and unavailable[0]["value_status"] == "unavailable"


def test_sleep_overlap_is_not_silently_summed():
    record = health_payload("sleep")
    record["samples"][0]["value"] = 999
    with pytest.raises(LifeError, match="LIFE_SLEEP_DURATION_MISMATCH"):
        health_batch(record, HEALTH, NOW, HEALTH.health_types)


def test_segment_candidates_have_evidence_and_unknown_gaps():
    mapped = location_batch({"locations": [point(0), point(5), point(50)]}, GPS, NOW)
    points = [
        {**strict_json(event["body"]), "event_id": str(i), "evidence_id": "evidence:" + str(i)}
        for i, event in enumerate(mapped)
    ]
    result = movement_segments(points, gap_seconds=600)
    assert result["unknown_gaps"] and result["segments"][0]["kind"] == "visit_candidate"
    assert result["segments"][0]["evidence_level"] == "inferred"
    assert result["segments"][0]["sample_count"] == 2
    assert result["segments"][0]["coverage_complete"] is False
    assert result["exact_places_inferred"] is False


def test_actual_generation_location_intake_preserves_original_batch(tmp_path):
    config, _root, principal = sensor_config(tmp_path)
    raw = {"locations": [point(0), point(5)], "trip": {"mode": "test"}}
    first = ingest(config, principal, "location", raw)
    again = ingest(config, principal, "location", raw)
    assert (
        first["result"] == "ok" and first["receipt_id"] == again["receipt_id"] and again["replayed"]
    )
    with read_root(config) as pinned, read_life_store(pinned) as store:
        events = store.events(principal, parse_settings(config.raw).policies)
        assert len(events) == 2
        raw_hash = store.connection.execute("SELECT raw_hash FROM life_sensor_batches").fetchone()[
            0
        ]
        assert (pinned / "raw" / raw_hash[:2] / raw_hash).read_bytes() == canonical(raw).encode()
        assert (
            store.receipt(first["receipt_id"], principal, parse_settings(config.raw).policies)[
                "events"
            ][0]["state"]
            == "captured_sensor"
        )
    processed = run_life_operation(config, "run", {}, principal, now=NOW)
    assert processed["processed"] == 0
    from sb.life_http import read_response

    with read_root(config) as pinned:
        _, segments = read_response(
            pinned,
            config,
            parse_settings(config.raw),
            principal,
            "/api/life/v1/location/segments",
            {},
            NOW,
        )
        assert segments["segments"]
        _, view = read_response(
            pinned,
            config,
            parse_settings(config.raw),
            principal,
            "/api/life/v1/views/obsidian/manifest",
            {},
            NOW,
        )
        assert "127.0" not in json.dumps(view)
        assert "37.5" not in json.dumps(view)


def test_generic_capture_cannot_bypass_sensor_type_policies(tmp_path):
    config, root, principal = sensor_config(tmp_path)
    event = location_batch({"locations": [point()]}, GPS, NOW)[0]
    before = root.resolve()
    with pytest.raises(LifeError, match="LIFE_USE_LOCATION_ENDPOINT"):
        run_life_operation(
            config, "capture", {"idempotency_key": "bypass", "events": [event]}, principal, now=NOW
        )
    assert root.resolve() == before


def test_health_anchor_only_advances_after_whole_transaction(tmp_path):
    config, root, principal = sensor_config(tmp_path)
    first = ingest(config, principal, "health", health_payload())
    assert first["result"] == "ok" and first["anchor"] == "anchor:1"
    old = root.resolve()
    with pytest.raises(LifeError, match="LIFE_HEALTH_ANCHOR_CONFLICT"):
        ingest(config, principal, "health", health_payload(anchor="anchor:2", samples=[]))
    assert root.resolve() == old
    second = ingest(
        config,
        principal,
        "health",
        health_payload(previous_anchor="anchor:1", anchor="anchor:2", samples=[]),
    )
    assert second["anchor"] == "anchor:2" and second["accepted_samples"] == 0


def test_health_deletion_blocks_late_source_reingress(tmp_path):
    config, _, principal = sensor_config(tmp_path)
    ingest(config, principal, "health", health_payload())
    removed = ingest(
        config,
        principal,
        "health",
        health_payload(
            previous_anchor="anchor:1", anchor="anchor:2", samples=[], deleted_ids=["sample:one"]
        ),
    )
    assert removed["deleted_samples"] == 1
    with read_root(config) as pinned, read_life_store(pinned) as store:
        assert not store.events(principal, parse_settings(config.raw).policies)
    with pytest.raises(LifeError, match="LIFE_EVENT_DELETED"):
        ingest(
            config,
            principal,
            "health",
            health_payload(previous_anchor="anchor:2", anchor="anchor:3"),
        )


def test_health_delete_unknown_sample_prevents_backfill_resurrection(tmp_path):
    config, _, principal = sensor_config(tmp_path)
    ingest(config, principal, "health", health_payload(samples=[], deleted_ids=["sample:one"]))
    with pytest.raises(LifeError, match="LIFE_EVENT_DELETED"):
        ingest(
            config,
            principal,
            "health",
            health_payload(previous_anchor="anchor:1", anchor="anchor:2"),
        )


def test_health_policy_and_feature_off_are_enforced(tmp_path):
    config, root, principal = sensor_config(tmp_path)
    config.raw["life"]["sources"][-1]["health_types"] = ["steps"]
    before = root.resolve()
    with pytest.raises(LifeError, match="LIFE_HEALTH_TYPE_NOT_ENABLED"):
        ingest(config, principal, "health", health_payload("hrv"))
    config.raw["life"]["features"]["health_capture"] = False
    with pytest.raises(LifeError, match="LIFE_FEATURE_DISABLED"):
        ingest(config, principal, "health", health_payload())
    assert root.resolve() == before
