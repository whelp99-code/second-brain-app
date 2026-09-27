"""Bounded Life source parsing; no persistence or network I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from sb.effect_values import JsonInput
from sb.life_attachments import inline
from sb.life_contracts import LifeInputError
from sb.life_json import LifePayload
from sb.life_sensor_values import number
from sb.life_values import canonical_bytes, instant, text

HEALTH_TYPES = frozenset({"sleep", "steps", "heart_rate", "hrv"})


HEALTH_UNITS = {"sleep": "min", "steps": "count", "heart_rate": "count/min", "hrv": "ms"}


def health_batch(
    document: JsonInput, *, allowed_types: Sequence[str], timezone: str, now: datetime
) -> tuple[tuple[LifePayload, ...], tuple[str, ...], str | None]:
    if not isinstance(document, dict) or set(document) - {"samples", "deleted", "anchor", "type"}:
        raise LifeInputError("LIFE_HEALTH_BATCH_INVALID")
    samples = document.get("samples", [])
    deleted_values = document.get("deleted", [])
    if (
        not isinstance(samples, list)
        or not isinstance(deleted_values, list)
        or len(samples) + len(deleted_values) > 1000
    ):
        raise LifeInputError("LIFE_HEALTH_BATCH_INVALID")
    batch_type = document.get("type")
    if batch_type not in HEALTH_TYPES or batch_type not in allowed_types:
        raise LifeInputError("LIFE_HEALTH_TYPE_DISABLED")
    anchor = document.get("anchor")
    if anchor is not None:
        anchor = text(anchor, maximum=65536)
    results: list[LifePayload] = []
    seen: set[str] = set()
    for row in samples:
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
        if not isinstance(kind, str) or kind != batch_type or kind not in allowed_types:
            raise LifeInputError("LIFE_HEALTH_TYPE_DISABLED")
        start, end = instant(row.get("start")), instant(row.get("end"))
        if end < start or end > now + timedelta(minutes=10):
            raise LifeInputError("LIFE_SENSOR_FUTURE_TIME")
        unit = row.get("unit")
        if not isinstance(unit, str) or unit != HEALTH_UNITS[kind]:
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
    deleted: list[str] = []
    for value in deleted_values:
        identity = text(value, maximum=256)
        if identity in seen:
            raise LifeInputError("LIFE_HEALTH_ADD_DELETE_CONFLICT")
        deleted.append("health:" + identity)
    return tuple(results), tuple(sorted(set(deleted))), anchor


def sleep_union(samples: Sequence[Mapping[str, JsonInput]]) -> LifePayload:
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
    totals: dict[str, float] = {}
    for source, intervals in groups.items():
        merged: list[tuple[datetime, datetime]] = []
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
