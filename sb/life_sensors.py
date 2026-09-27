"""Pure opt-in location/health mapping and deterministic movement segmentation.

No device API, network, medical interpretation, or per-point LLM call.
Original sensor batches are preserved by the orchestration layer separately.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import pairwise

from sb.life_contracts import (
    LifeError,
    LifeEventV1,
    SourcePolicyV1,
    canonical,
    digest,
    identifier,
    instant,
    integer,
    number,
    object_fields,
    stamp,
    text,
)

HEALTH_UNITS = {"sleep": "seconds", "steps": "count", "heart_rate": "beats/min", "hrv": "ms"}
SLEEP_STAGES = frozenset(
    {"in_bed", "asleep", "awake", "asleep_core", "asleep_deep", "asleep_rem", "unknown"}
)


def location_batch(payload: object, source: SourcePolicyV1, now: datetime) -> tuple[dict, ...]:
    obj = object_fields(payload, {"locations", "current", "trip"}, {"locations"})
    locations = obj["locations"]
    if not isinstance(locations, list) or not 1 <= len(locations) <= 1000:
        raise LifeError("LIFE_LOCATION_BATCH_INVALID")
    if source.sensitivity != "restricted" or source.external_processing != "local_only":
        raise LifeError("LIFE_LOCATION_POLICY_REQUIRED", 403)
    results = []
    seen = set()
    for feature in locations:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise LifeError("LIFE_LOCATION_FEATURE_INVALID")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(properties, dict)
        ):
            raise LifeError("LIFE_LOCATION_GEOMETRY_UNSUPPORTED")
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) not in {2, 3}:
            raise LifeError("LIFE_LOCATION_COORDINATES_INVALID")
        longitude = number(coords[0], minimum=-180, maximum=180)
        latitude = number(coords[1], minimum=-90, maximum=90)
        observed = instant(properties.get("timestamp"))
        if observed > now:
            raise LifeError("LIFE_LOCATION_FUTURE_OBSERVATION", 422)
        accuracy_raw = properties.get("horizontal_accuracy")
        accuracy = (
            None if accuracy_raw is None else number(accuracy_raw, minimum=-1, maximum=100000)
        )
        if accuracy is not None and accuracy < 0:
            accuracy = None
        speed_raw = properties.get("speed")
        speed = None if speed_raw is None else number(speed_raw, minimum=-1, maximum=1000)
        if speed is not None and speed < 0:
            speed = None
        device = text(
            properties.get("unique_id") or properties.get("device_id") or "unspecified", maximum=256
        )
        normalized = {
            "schema_version": 1,
            "kind": "location_point",
            "timestamp": stamp(observed),
            "longitude": longitude,
            "latitude": latitude,
            "accuracy_m": accuracy,
            "speed_mps": speed,
            "device_id_digest": digest(source.source_id + "\0" + device),
            "value_status": "observed" if accuracy is not None else "unavailable",
        }
        version = digest(canonical(normalized))
        # Batch-size/battery telemetry does not create a new identical position fix.
        source_item = "location:" + version
        if source_item in seen:
            continue
        seen.add(source_item)
        results.append(
            {
                "source_id": source.source_id,
                "source_item_id": source_item,
                "source_version": version,
                "title": "위치 관측",
                "body": canonical(normalized),
                "event_type": "location_point",
                "event_status": "occurred",
                "evidence_level": "observed",
                "occurred_start": stamp(observed),
                "observed_at": stamp(observed),
                "timezone": "Asia/Seoul",
                "time_precision": "exact",
                "sensitivity": "restricted",
                "external_processing": "local_only",
            }
        )
    return tuple(results)


def health_batch(
    payload: object, source: SourcePolicyV1, now: datetime, allowed_types: Sequence[str]
) -> tuple[dict, tuple[dict, ...], tuple[str, ...]]:
    obj = object_fields(
        payload,
        {
            "schema_version",
            "device_id",
            "health_type",
            "previous_anchor",
            "anchor",
            "samples",
            "deleted_ids",
        },
        {
            "schema_version",
            "device_id",
            "health_type",
            "previous_anchor",
            "anchor",
            "samples",
            "deleted_ids",
        },
    )
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise LifeError("LIFE_HEALTH_SCHEMA_UNSUPPORTED")
    device_id = identifier(obj["device_id"])
    kind = obj["health_type"]
    if kind not in HEALTH_UNITS or kind not in allowed_types:
        raise LifeError("LIFE_HEALTH_TYPE_NOT_ENABLED", 403)
    if source.sensitivity != "restricted" or source.external_processing != "local_only":
        raise LifeError("LIFE_HEALTH_POLICY_REQUIRED", 403)
    previous = (
        None if obj["previous_anchor"] is None else text(obj["previous_anchor"], maximum=16384)
    )
    anchor = text(obj["anchor"], maximum=16384)
    samples, deleted = obj["samples"], obj["deleted_ids"]
    if (
        not isinstance(samples, list)
        or not isinstance(deleted, list)
        or len(samples) + len(deleted) > 1000
    ):
        raise LifeError("LIFE_HEALTH_BATCH_INVALID")
    deleted_ids = tuple(identifier(value) for value in deleted)
    if len(deleted_ids) != len(set(deleted_ids)):
        raise LifeError("LIFE_HEALTH_DUPLICATE_DELETION")
    results, sample_ids = [], set()
    for raw in samples:
        item = object_fields(
            raw,
            {"sample_id", "start", "end", "value", "unit", "source_bundle_id", "sleep_stage"},
            {"sample_id", "start", "end", "value", "unit", "source_bundle_id"},
        )
        sample_id = identifier(item["sample_id"])
        if sample_id in sample_ids or sample_id in deleted_ids:
            raise LifeError("LIFE_HEALTH_CONFLICTING_SAMPLE")
        sample_ids.add(sample_id)
        start, end = instant(item["start"]), instant(item["end"])
        if end < start or end > now:
            raise LifeError("LIFE_HEALTH_TIME_INVALID")
        if item["unit"] != HEALTH_UNITS[kind]:
            raise LifeError("LIFE_HEALTH_UNIT_INVALID")
        value = None if item["value"] is None else number(item["value"], minimum=0, maximum=1e12)
        stage = item.get("sleep_stage")
        if kind == "sleep":
            if stage not in SLEEP_STAGES:
                raise LifeError("LIFE_SLEEP_STAGE_INVALID")
            expected = (end - start).total_seconds()
            if value is not None and abs(value - expected) > 0.001:
                raise LifeError("LIFE_SLEEP_DURATION_MISMATCH")
        elif stage is not None:
            raise LifeError("LIFE_HEALTH_FIELDS_INVALID")
        normalized = {
            "schema_version": 1,
            "health_type": kind,
            "sample_id": sample_id,
            "device_id_digest": digest(device_id),
            "start": stamp(start),
            "end": stamp(end),
            "value": value,
            "value_status": "unavailable" if value is None else "observed",
            "unit": HEALTH_UNITS[kind],
            "source_bundle_id": text(item["source_bundle_id"], maximum=256),
            "sleep_stage": stage,
        }
        source_item = "health:" + digest(device_id + "\0" + kind + "\0" + sample_id)
        results.append(
            {
                "source_id": source.source_id,
                "source_item_id": source_item,
                "source_version": digest(canonical(normalized)),
                "title": "건강 표본 · " + kind,
                "body": canonical(normalized),
                "event_type": "health_sample",
                "event_status": "occurred",
                "evidence_level": "observed",
                "occurred_start": stamp(start),
                "occurred_end": stamp(end),
                "observed_at": stamp(end),
                "timezone": "Asia/Seoul",
                "time_precision": "exact",
                "sensitivity": "restricted",
                "external_processing": "local_only",
                "value": value,
                "value_status": normalized["value_status"],
                "unit": HEALTH_UNITS[kind],
            }
        )
    deleted_items = tuple(
        "health:" + digest(device_id + "\0" + kind + "\0" + sample_id) for sample_id in deleted_ids
    )
    cursor = {
        "stream_id": digest(source.source_id + "\0" + device_id + "\0" + kind),
        "previous_anchor": previous,
        "anchor": anchor,
        "health_type": kind,
    }
    return cursor, tuple(results), deleted_items


def distance_m(a: Mapping, b: Mapping) -> float:
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dlat, dlon = lat2 - lat1, math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(max(0, h))))


def movement_segments(
    points: Sequence[Mapping],
    *,
    max_accuracy_m: float = 100,
    gap_seconds: int = 1800,
    visit_radius_m: float = 150,
    minimum_visit_seconds: int = 180,
) -> dict:
    number(max_accuracy_m, minimum=1, maximum=100000)
    number(visit_radius_m, minimum=1, maximum=100000)
    integer(gap_seconds, minimum=1, maximum=86400)
    integer(minimum_visit_seconds, minimum=1, maximum=86400)
    if len(points) > 10000:
        raise LifeError("LIFE_SEGMENT_POINT_LIMIT", 413)
    groups: dict[str, list[Mapping]] = {}
    rejected = 0
    for point in points:
        if point.get("accuracy_m") is None or point["accuracy_m"] > max_accuracy_m:
            rejected += 1
            continue
        groups.setdefault(point["device_id_digest"], []).append(point)
    segments, gaps = [], []
    for device_id, records in sorted(groups.items()):
        records.sort(key=lambda row: (row["timestamp"], row.get("event_id", "")))
        chunk: list[Mapping] = []

        def emit(items: Sequence[Mapping], device: str = device_id) -> None:
            if len(items) < 2:
                return
            start, end = instant(items[0]["timestamp"]), instant(items[-1]["timestamp"])
            elapsed = (end - start).total_seconds()
            radius = max(distance_m(items[0], point) for point in items)
            kind = (
                "visit_candidate"
                if radius <= visit_radius_m and elapsed >= minimum_visit_seconds
                else "movement_observation"
            )
            segments.append(
                {
                    "segment_id": "segment:"
                    + digest(device + "\0" + items[0]["timestamp"] + "\0" + items[-1]["timestamp"]),
                    "kind": kind,
                    "start": stamp(start),
                    "end": stamp(end),
                    "duration_seconds": elapsed,
                    "observed_path_m": sum(distance_m(a, b) for a, b in pairwise(items)),
                    "sample_count": len(items),
                    "evidence_level": "inferred",
                    "evidence_ids": [point["evidence_id"] for point in items],
                    "coverage_complete": False,
                }
            )

        for point in records:
            if (
                chunk
                and (instant(point["timestamp"]) - instant(chunk[-1]["timestamp"])).total_seconds()
                > gap_seconds
            ):
                gaps.append(
                    {"start": chunk[-1]["timestamp"], "end": point["timestamp"], "state": "unknown"}
                )
                emit(chunk)
                chunk = []
            # Separate stationary/moving clusters rather than labeling an entire day a visit.
            if (
                chunk
                and distance_m(chunk[0], point) > visit_radius_m
                and (
                    instant(chunk[-1]["timestamp"]) - instant(chunk[0]["timestamp"])
                ).total_seconds()
                >= minimum_visit_seconds
            ):
                emit(chunk)
                chunk = [chunk[-1]]
            chunk.append(point)
        emit(chunk)
    return {
        "algorithm": "bounded-location-segments-v1",
        "segments": segments,
        "unknown_gaps": gaps,
        "excluded_low_accuracy": rejected,
        "exact_places_inferred": False,
        "note": "관측 간 이동 추정이며 실제 전체 경로·방문·교통 상황을 보장하지 않습니다.",
    }


def summarize_health(events: Sequence[LifeEventV1]) -> dict:
    """Group source samples without summing overlapping providers or sleep stages."""
    from sb.life_contracts import strict_json

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for event in events:
        if event.event_type != "health_sample":
            continue
        item = strict_json(event.body)
        key = (event.source_id, item["health_type"], item["source_bundle_id"])
        groups.setdefault(key, []).append(item)
    summaries = []
    for (source, kind, provider), samples in sorted(groups.items()):
        observed = [sample["value"] for sample in samples if sample["value"] is not None]
        summaries.append(
            {
                "source_id": source,
                "health_type": kind,
                "source_bundle_id": provider,
                "sample_count": len(samples),
                "observed_count": len(observed),
                "missing_count": len(samples) - len(observed),
                "unit": HEALTH_UNITS[kind],
                "minimum": min(observed) if observed else None,
                "maximum": max(observed) if observed else None,
                "total": None,
                "total_state": "not_aggregated_across_overlaps_or_providers",
            }
        )
    return {"groups": summaries, "diagnosis": None, "read_authorization_inferred": False}
