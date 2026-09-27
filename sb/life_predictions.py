"""Immutable, cutoff-bound duration forecasts and separately versioned results.

This is a deterministic baseline, not a claimed learned personal model. No medical,
financial or relationship predictions. Missing results remain unscored.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from statistics import median

from sb.effect_values import JsonInput
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_fields import number
from sb.life_journal_contracts import JournalRow
from sb.life_json import LifePayload
from sb.life_values import instant, text
from sb.store.life_journal import LifeJournal, evidence_refs, identity


def duration_minutes(event: LifeEventV1) -> float | None:
    if event.event_status != "occurred" or event.event_type not in {
        "location_trip",
        "task_completed",
    }:
        return None
    if event.value_status == "observed" and event.value is not None:
        value = float(event.value)
        if event.unit in {"min", "minute", "minutes"}:
            result = value
        elif event.unit in {"s", "second", "seconds"}:
            result = value / 60
        else:
            return None
    elif event.occurred_start is not None and event.occurred_end is not None:
        result = (instant(event.occurred_end) - instant(event.occurred_start)).total_seconds() / 60
    else:
        return None
    return result if math.isfinite(result) and 0 < result <= 7 * 24 * 60 else None


def issue(
    journal: LifeJournal,
    data: Mapping[str, JsonInput],
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    if set(data) - {
        "target_id",
        "target_start",
        "target_end",
        "event_type",
        "input_cutoff_at",
        "minimum_samples",
        "idempotency_key",
    }:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    target_id = text(data.get("target_id"), maximum=160)
    key = text(data.get("idempotency_key"), maximum=256)
    target_start, target_end = instant(data.get("target_start")), instant(data.get("target_end"))
    cutoff = instant(data.get("input_cutoff_at", now.isoformat()))
    event_type = data.get("event_type")
    minimum = data.get("minimum_samples", 20)
    if (
        event_type not in {"location_trip", "task_completed"}
        or type(minimum) is not int
        or not 2 <= minimum <= 1000
    ):
        raise LifeInputError("LIFE_PREDICTION_INVALID")
    if not cutoff <= now <= target_start < target_end:
        raise LifeInputError("LIFE_PREDICTION_CUTOFF_INVALID")
    pid = identity("prediction", [scopes, source_ids, key])
    prior = journal.raw("prediction", pid)
    request = dict(data)
    if prior is not None:
        if prior["body"].get("request") != request:
            raise LifeInputError("LIFE_IDEMPOTENCY_CONFLICT")
        return journal.get(
            "prediction",
            pid,
            scopes=scopes,
            source_ids=source_ids,
            events=events,
            require_current=False,
        )
    eligible: list[tuple[LifeEventV1, float]] = []
    for event in events:
        value = duration_minutes(event)
        ended = event.occurred_end or event.occurred_start
        if (
            event.event_type == event_type
            and value is not None
            and ended is not None
            and instant(ended) <= cutoff
            and instant(event.recorded_at) <= cutoff
        ):
            eligible.append((event, value))
    eligible.sort(
        key=lambda pair: (pair[0].occurred_end or pair[0].occurred_start or "", pair[0].event_id)
    )
    eligible = eligible[-500:]
    values = [pair[1] for pair in eligible]
    ready = len(values) >= minimum
    ordered = sorted(values)
    estimate = float(median(values)) if ready else None
    interval = (
        [ordered[int((len(ordered) - 1) * 0.1)], ordered[int((len(ordered) - 1) * 0.9)]]
        if ready
        else None
    )
    body = {
        "request": request,
        "target_id": target_id,
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "event_type": event_type,
        "issued_at": now.isoformat(),
        "input_cutoff_at": cutoff.isoformat(),
        "sample_count": len(values),
        "minimum_samples": minimum,
        "state": "issued" if ready else "insufficient_data",
        "estimate_minutes": estimate,
        "empirical_interval_minutes": interval,
        "interval_is_calibrated": False,
        "baseline_recent_minutes": values[-1] if ready else None,
        "baseline_median_minutes": estimate,
        "rule_version": "duration-median-v1",
        "evidence_snapshot": evidence_refs([pair[0] for pair in eligible]),
        "statistical_sufficiency_claimed": False,
    }
    return journal.put(
        "prediction",
        pid,
        body,
        events=tuple(pair[0] for pair in eligible),
        scopes=scopes,
        source_ids=source_ids,
        now=now,
    )


def evaluate(
    journal: LifeJournal,
    prediction_id: str,
    *,
    actual_id: str,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    prediction = journal.get(
        "prediction",
        prediction_id,
        scopes=scopes,
        source_ids=source_ids,
        events=events,
        require_current=False,
    )
    p = prediction["body"]
    matches = [e for e in events if e.event_id == actual_id or e.source_item_id == actual_id]
    if len(matches) != 1:
        raise LifeInputError("LIFE_PREDICTION_TARGET_MISMATCH")
    actual = matches[0]
    # Explicit stable identity, never nearest semantic match.
    if actual.event_id != p["target_id"] and actual.source_item_id != p["target_id"]:
        raise LifeInputError("LIFE_PREDICTION_TARGET_MISMATCH")
    if actual.event_type != p["event_type"]:
        raise LifeInputError("LIFE_PREDICTION_TARGET_MISMATCH")
    value = duration_minutes(actual)
    valid_start = actual.occurred_start is not None and (
        instant(p["target_start"]) <= instant(actual.occurred_start) < instant(p["target_end"])
        and instant(actual.occurred_start) >= instant(p["issued_at"])
    )
    if not valid_start or instant(actual.recorded_at) < instant(p["issued_at"]):
        state = "ineligible"
    elif value is None or p["state"] != "issued":
        state = "unscored"
    else:
        state = "scored"
    error = (
        value - number(p["estimate_minutes"]) if state == "scored" and value is not None else None
    )
    body = {
        "prediction_id": prediction_id,
        "actual_event_id": actual.event_id,
        "actual_revision": actual.revision,
        "actual_minutes": value,
        "state": state,
        "evaluated_at": now.isoformat(),
        "signed_error_minutes": error,
        "absolute_error_minutes": abs(error) if error is not None else None,
        "recent_baseline_absolute_error": abs(value - number(p["baseline_recent_minutes"]))
        if state == "scored" and value is not None
        else None,
        "initial_prediction_unchanged": True,
    }
    aid = identity("actual", prediction_id)
    prior = journal.raw("actual", aid)
    if prior is not None and prior["body"].get("actual_revision") == actual.revision:
        return journal.get("actual", aid, scopes=scopes, source_ids=source_ids, events=events)
    training_ids = {ref["event_id"] for ref in prediction["evidence"]}
    refs = tuple(e for e in events if e.event_id in training_ids or e.event_id == actual.event_id)
    return journal.put(
        "actual",
        aid,
        body,
        events=refs,
        scopes=tuple(prediction["scopes"]),
        source_ids=tuple(prediction["source_ids"]),
        now=now,
        expected_revision=0 if prior is None else prior["revision"],
    )


def metrics(rows: Sequence[JournalRow]) -> LifePayload:
    scored = [r["body"] for r in rows if r["body"].get("state") == "scored"]
    if not scored:
        return {
            "state": "unscored",
            "count": 0,
            "mae_minutes": None,
            "recent_baseline_mae_minutes": None,
        }
    mean_error = sum(number(r["absolute_error_minutes"]) for r in scored) / len(scored)
    baseline = sum(number(r["recent_baseline_absolute_error"]) for r in scored) / len(scored)
    return {
        "state": "measured",
        "count": len(scored),
        "mae_minutes": mean_error,
        "recent_baseline_mae_minutes": baseline,
        "generalization_claimed": False,
    }
