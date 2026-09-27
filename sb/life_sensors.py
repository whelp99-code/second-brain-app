"""Deterministic, local-only sensor normalization; no account or model access.

Overland coordinates remain in restricted raw evidence. Health values preserve
units, source and missingness; no physiological or medical interpretation.
"""

from __future__ import annotations

from sb.life_health import HEALTH_TYPES, HEALTH_UNITS, health_batch, sleep_union
from sb.life_sensor_values import number

__all__ = [
    "HEALTH_TYPES",
    "HEALTH_UNITS",
    "Point",
    "distance",
    "health_batch",
    "number",
    "parse_overland",
    "point_payload",
    "segments",
    "sleep_union",
]

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import pairwise

from sb.effect_values import JsonInput
from sb.life_attachments import inline
from sb.life_contracts import LifeInputError
from sb.life_json import LifePayload
from sb.life_values import canonical_bytes, instant, text


@dataclass(frozen=True, slots=True)
class Point:
    source_item_id: str
    at: datetime
    latitude: float
    longitude: float
    accuracy: float | None
    raw: LifePayload


def parse_overland(document: JsonInput, *, now: datetime) -> tuple[Point, ...]:
    if not isinstance(document, dict) or set(document) - {"locations", "current", "trip"}:
        raise LifeInputError("LIFE_LOCATION_BATCH_INVALID")
    locations = document.get("locations")
    if not isinstance(locations, list) or len(locations) > 1000:
        raise LifeInputError("LIFE_LOCATION_BATCH_INVALID")
    rows = list(locations)
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


def point_payload(point: Point, *, timezone: str = "Asia/Seoul") -> LifePayload:
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
) -> tuple[LifePayload, ...]:
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
    result: list[LifePayload] = []
    for group in chunks:
        if len(group) < 2:
            continue
        groups: list[list[Point]] = []
        current = [group[0]]
        stationary = None
        for point in group[1:]:
            moving = distance(current[-1], point) > max(
                radius_meters, (current[-1].accuracy or 0) + (point.accuracy or 0)
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
                distance(start, p) <= radius_meters + (start.accuracy or 0) + (p.accuracy or 0)
                for p in part
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
