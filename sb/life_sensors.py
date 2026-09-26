"""Deterministic, local-only sensor normalization; no account or model access.

Overland coordinates remain in restricted raw evidence. Health values preserve
units, source and missingness; no physiological or medical interpretation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import pairwise
from typing import Any

from sb.life_attachments import inline
from sb.life_contracts import LifeInputError
from sb.life_values import canonical_bytes, instant, text

HEALTH_TYPES = frozenset({"sleep", "steps", "heart_rate", "hrv"})
HEALTH_UNITS = {"sleep": "min", "steps": "count", "heart_rate": "count/min", "hrv": "ms"}


def number(value: object, lower: float, upper: float) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or not lower <= value <= upper:
        raise LifeInputError("LIFE_SENSOR_NUMBER_INVALID")
    return float(value)


@dataclass(frozen=True, slots=True)
class Point:
    source_item_id: str
    at: datetime
    latitude: float
    longitude: float
    accuracy: float | None
    raw: dict[str, Any]


def parse_overland(document: object, *, now: datetime) -> tuple[Point, ...]:
    if (
        not isinstance(document, dict)
        or set(document) - {"locations", "current", "trip"}
        or not isinstance(document.get("locations"), list)
        or len(document["locations"]) > 1000
    ):
        raise LifeInputError("LIFE_LOCATION_BATCH_INVALID")
    rows = list(document["locations"])
    # `current` is a distinct recent point when older batches are queued.
    if document.get("current") is not None:
        rows.append(document["current"])
    selected: dict[str, Point] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "Feature":
            raise LifeInputError("LIFE_LOCATION_INVALID")
        geometry = row.get("geometry")
        properties = row.get("properties")
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(properties, dict)
        ):
            raise LifeInputError("LIFE_LOCATION_INVALID")
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) not in {2, 3}:
            raise LifeInputError("LIFE_LOCATION_INVALID")
        longitude = number(coords[0], -180, 180)
        latitude = number(coords[1], -90, 90)
        at = instant(properties.get("timestamp"))
        if at > now + timedelta(minutes=10):
            raise LifeInputError("LIFE_SENSOR_FUTURE_TIME")
        accuracy = properties.get("horizontal_accuracy")
        accuracy = None if accuracy is None or accuracy == -1 else number(accuracy, 0, 100000)
        device = text(properties.get("device_id", ""), maximum=256, empty=True)
        # Device id and observation identity, not delivery batch membership.
        source_id = (
            "overland:"
            + sha256(canonical_bytes([device, at.isoformat(), latitude, longitude])).hexdigest()
        )
        point = Point(source_id, at, latitude, longitude, accuracy, row)
        if source_id in selected and canonical_bytes(selected[source_id].raw) != canonical_bytes(
            row
        ):
            raise LifeInputError("LIFE_SOURCE_VERSION_CONFLICT")
        selected[source_id] = point
    return tuple(sorted(selected.values(), key=lambda p: (p.at, p.source_item_id)))


def point_payload(point: Point, *, timezone: str = "Asia/Seoul") -> dict[str, object]:
    raw = canonical_bytes(point.raw)
    return {
        "source_item_id": point.source_item_id,
        "source_version": sha256(raw).hexdigest(),
        "event_type": "location_point",
        "title": "위치 관측",
        "body": "정확한 좌표는 제한된 원문에 보관합니다. 방문·미팅 진행의 증거로 단정하지 않습니다.",
        "occurred_start": point.at.isoformat(),
        "observed_at": point.at.isoformat(),
        "timezone": timezone,
        "time_precision": "exact",
        "event_status": "occurred",
        "evidence_level": "observed",
        "value": point.accuracy,
        "value_status": "observed" if point.accuracy is not None else "unavailable",
        "unit": "m",
        "attachments": [inline("overland-point.json", "application/json", raw)],
    }


def distance(left: Point, right: Point) -> float:
    lat1, lat2 = math.radians(left.latitude), math.radians(right.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(right.longitude - left.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(value)))


def segments(
    points: Sequence[Point],
    *,
    timezone: str = "Asia/Seoul",
    gap_seconds: int = 900,
    radius_meters: float = 200,
    max_accuracy: float = 100,
    dwell_seconds: int = 300,
) -> tuple[dict[str, object], ...]:
    if (
        not 1 <= gap_seconds <= 3600
        or not 10 <= radius_meters <= 5000
        or not 1 <= dwell_seconds <= 86400
    ):
        raise LifeInputError("LIFE_LOCATION_CONFIG_INVALID")
    ordered = sorted(
        {p.source_item_id: p for p in points}.values(), key=lambda p: (p.at, p.source_item_id)
    )
    chunks: list[list[Point]] = []
    for point in ordered:
        if point.accuracy is None or point.accuracy > max_accuracy:
            if chunks and chunks[-1]:
                chunks.append([])
            continue
        if not chunks:
            chunks.append([])
        if chunks[-1] and (point.at - chunks[-1][-1].at).total_seconds() > gap_seconds:
            chunks.append([])
        chunks[-1].append(point)
    result = []
    for group in chunks:
        if len(group) < 2:
            continue
        groups: list[list[Point]] = []
        current = [group[0]]
        stationary = None
        for point in group[1:]:
            moving = distance(current[-1], point) > max(
                radius_meters, current[-1].accuracy + point.accuracy
            )
            kind = not moving
            if stationary is not None and kind != stationary:
                groups.append(current)
                current = [current[-1]]
            stationary = kind
            current.append(point)
        groups.append(current)
        for part in groups:
            start, end = part[0], part[-1]
            seconds = (end.at - start.at).total_seconds()
            if seconds <= 0:
                continue
            traveled = sum(distance(a, b) for a, b in pairwise(part))
            stopped = all(
                distance(start, p) <= radius_meters + start.accuracy + p.accuracy for p in part
            )
            if stopped and seconds < dwell_seconds:
                continue
            kind = "location_visit" if stopped else "location_trip"
            refs = [p.source_item_id for p in part]
            raw = {
                "algorithm": "bounded-location-segments-v1",
                "points": refs,
                "start": start.at.isoformat(),
                "end": end.at.isoformat(),
                "distance_meters": round(traveled, 2),
                "gap_seconds": gap_seconds,
                "radius_meters": radius_meters,
                "accuracy_limit": max_accuracy,
            }
            key = kind + ":" + sha256(canonical_bytes([refs[0], refs[-1], kind])).hexdigest()
            result.append(
                {
                    "source_item_id": key,
                    "source_version": sha256(canonical_bytes(raw)).hexdigest(),
                    "event_type": kind,
                    "title": "체류 구간 추정" if stopped else "이동 구간 추정",
                    "body": "연속된 위치 관측의 결정적 집계입니다. 기록 사이의 이동이나 미팅은 확정하지 않습니다.",
                    "occurred_start": start.at.isoformat(),
                    "occurred_end": end.at.isoformat(),
                    "timezone": timezone,
                    "time_precision": "range",
                    "event_status": "occurred",
                    "evidence_level": "inferred",
                    "value": seconds / 60,
                    "value_status": "observed",
                    "unit": "min",
                    "attachments": [
                        inline("location-segment.json", "application/json", canonical_bytes(raw))
                    ],
                }
            )
    return tuple(result)


def health_batch(
    document: object, *, allowed_types: Sequence[str], timezone: str, now: datetime
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...], str | None]:
    if (
        not isinstance(document, dict)
        or set(document) - {"samples", "deleted", "anchor", "type"}
        or not isinstance(document.get("samples", []), list)
        or not isinstance(document.get("deleted", []), list)
        or len(document.get("samples", [])) + len(document.get("deleted", [])) > 1000
    ):
        raise LifeInputError("LIFE_HEALTH_BATCH_INVALID")
    batch_type = document.get("type")
    if batch_type not in HEALTH_TYPES or batch_type not in allowed_types:
        raise LifeInputError("LIFE_HEALTH_TYPE_DISABLED")
    anchor = document.get("anchor")
    if anchor is not None:
        text(anchor, maximum=65536)
    results = []
    seen = set()
    for row in document.get("samples", []):
        if not isinstance(row, dict) or set(row) - {
            "id",
            "type",
            "start",
            "end",
            "value",
            "unit",
            "source",
            "sleep_stage",
            "value_status",
        }:
            raise LifeInputError("LIFE_HEALTH_SAMPLE_INVALID")
        identity = text(row.get("id"), maximum=256)
        if identity in seen:
            raise LifeInputError("LIFE_HEALTH_DUPLICATE_SAMPLE")
        seen.add(identity)
        kind = row.get("type")
        if kind != batch_type or kind not in allowed_types:
            raise LifeInputError("LIFE_HEALTH_TYPE_DISABLED")
        start, end = instant(row.get("start")), instant(row.get("end"))
        if end < start or end > now + timedelta(minutes=10):
            raise LifeInputError("LIFE_SENSOR_FUTURE_TIME")
        unit = row.get("unit")
        if unit != HEALTH_UNITS[kind]:
            raise LifeInputError("LIFE_HEALTH_UNIT_INVALID")
        status = row.get("value_status", "observed")
        value = row.get("value")
        if status not in {"observed", "missing", "unavailable"}:
            raise LifeInputError("LIFE_HEALTH_SAMPLE_INVALID")
        if status == "observed":
            value = number(value, 0, 10000000)
        elif value is not None:
            raise LifeInputError("LIFE_VALUE_STATE_MISMATCH")
        source = text(row.get("source", "unknown"), maximum=256)
        stage = row.get("sleep_stage")
        if stage is not None and (
            kind != "sleep" or type(stage) is not int or not 0 <= stage <= 16
        ):
            raise LifeInputError("LIFE_HEALTH_SAMPLE_INVALID")
        raw = canonical_bytes(row)
        results.append(
            {
                "source_item_id": "health:" + identity,
                "source_version": sha256(raw).hexdigest(),
                "event_type": "health_sample",
                "title": {
                    "sleep": "수면 구간",
                    "steps": "걸음 수",
                    "heart_rate": "심박 측정",
                    "hrv": "HRV 측정",
                }[kind],
                "body": "출처: "
                + source
                + "\n종류: "
                + kind
                + "\n단위: "
                + unit
                + ("\n수면 단계 코드: " + str(stage) if stage is not None else "")
                + "\n센서 관측값이며 건강 상태나 진단을 의미하지 않습니다.",
                "occurred_start": start.isoformat(),
                "occurred_end": end.isoformat(),
                "observed_at": end.isoformat(),
                "timezone": timezone,
                "time_precision": "range" if end > start else "exact",
                "event_status": "occurred",
                "evidence_level": "observed",
                "value": value,
                "value_status": status,
                "unit": unit,
                "attachments": [inline("health-sample.json", "application/json", raw)],
            }
        )
    deleted = []
    for value in document.get("deleted", []):
        identity = text(value, maximum=256)
        if identity in seen:
            raise LifeInputError("LIFE_HEALTH_ADD_DELETE_CONFLICT")
        deleted.append("health:" + identity)
    return tuple(results), tuple(sorted(set(deleted))), anchor


def sleep_union(samples: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Union overlapping sleep intervals per source, not a cross-device sum."""
    groups: dict[str, list[tuple[datetime, datetime]]] = {}
    for row in samples:
        if row.get("type") != "sleep" or row.get("value_status", "observed") != "observed":
            continue
        # inBed(0) and awake(2) are not sleep minutes.
        if row.get("sleep_stage") in {0, 2}:
            continue
        start, end = instant(row["start"]), instant(row["end"])
        if end < start:
            raise LifeInputError("LIFE_HEALTH_SAMPLE_INVALID")
        groups.setdefault(str(row.get("source", "unknown")), []).append((start, end))
    totals = {}
    for source, intervals in groups.items():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        totals[source] = sum((end - start).total_seconds() / 60 for start, end in merged)
    return {
        "minutes_by_source": totals,
        "combined_minutes": next(iter(totals.values())) if len(totals) == 1 else None,
        "state": "no_data"
        if not totals
        else "source_conflict"
        if len(totals) > 1
        else "observed_union",
    }
