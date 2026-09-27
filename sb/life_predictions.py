"""Pre-outcome duration predictions and versioned actuals, using the existing ledger.

The initial estimator is a transparent median baseline, not a claimed trained
personal model. Inputs are fixed before the target and always evidence-linked.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from statistics import median

from sb.life_config import LifeSettings
from sb.life_contracts import (
    LifeError,
    LifeEventV1,
    LifePrincipal,
    canonical,
    digest,
    identifier,
    instant,
    integer,
    object_fields,
    stamp,
    strict_json,
)
from sb.life_store import LifeStore

TARGET_TYPES = frozenset({"activity", "calendar_event", "location_trip"})


def duration(event: LifeEventV1) -> float | None:
    if (
        event.event_status != "occurred"
        or event.occurred_start is None
        or event.occurred_end is None
    ):
        return None
    seconds = (instant(event.occurred_end) - instant(event.occurred_start)).total_seconds()
    return seconds if seconds >= 0 else None


def _load(store: LifeStore, prediction_id: str) -> dict:
    identifier(prediction_id)
    if not store.ready:
        raise LifeError("LIFE_PREDICTION_NOT_FOUND", 404)
    row = store.connection.execute(
        "SELECT prediction_json,content_digest FROM life_predictions WHERE prediction_id=?",
        (prediction_id,),
    ).fetchone()
    if row is None:
        raise LifeError("LIFE_PREDICTION_NOT_FOUND", 404)
    if digest(row[0]) != row[1]:
        raise LifeError("LIFE_PREDICTION_INTEGRITY", 503)
    return strict_json(row[0])


def authorized_prediction(
    store: LifeStore, prediction_id: str, principal: LifePrincipal, settings: LifeSettings
) -> dict:
    result = _load(store, prediction_id)
    try:
        target = store.authorized_event(result["target_id"], principal, settings.policies)
        if target.scope != result["scope"]:
            raise LifeError("LIFE_PREDICTION_NOT_FOUND", 404)
        for sample in result["evidence_snapshot"]:
            event = store.authorized_event(sample["event_id"], principal, settings.policies)
            if event.scope != target.scope:
                raise LifeError("LIFE_PREDICTION_NOT_FOUND", 404)
    except LifeError as exc:
        if exc.status in {403, 404}:
            raise LifeError("LIFE_PREDICTION_NOT_FOUND", 404) from exc
        raise
    return result


def issue(
    store: LifeStore, data: Mapping, settings: LifeSettings, principal: LifePrincipal, now: datetime
) -> dict:
    settings.require("prediction")
    if "predict" not in principal.operations:
        raise LifeError("LIFE_OPERATION_FORBIDDEN", 403)
    obj = object_fields(
        data,
        {"idempotency_key", "target_id", "sample_event_ids", "input_cutoff_at"},
        {"idempotency_key", "target_id", "sample_event_ids"},
    )
    key = identifier(obj["idempotency_key"])
    target_id = identifier(obj["target_id"])
    sample_ids = obj["sample_event_ids"]
    if not isinstance(sample_ids, list) or len(sample_ids) > 5000:
        raise LifeError("LIFE_PREDICTION_SAMPLES_INVALID")
    sample_ids = [identifier(value) for value in sample_ids]
    if len(sample_ids) != len(set(sample_ids)) or target_id in sample_ids:
        raise LifeError("LIFE_PREDICTION_SAMPLES_INVALID")
    request_digest = digest(canonical({"operation": "prediction_issue", **obj}))
    prediction_id = "prediction:" + digest(principal.client_id + "\0" + key)
    with store.transaction():
        replay = store._replay(principal.client_id, key, request_digest)
        if replay:
            result = authorized_prediction(store, prediction_id, principal, settings)
            return {**result, "receipt_id": replay, "replayed": True}
        target = store.authorized_event(target_id, principal, settings.policies)
        if target.event_type not in TARGET_TYPES or target.event_status not in {
            "planned",
            "unknown",
        }:
            raise LifeError("LIFE_PREDICTION_TARGET_INELIGIBLE", 422)
        if target.occurred_start is None or instant(target.occurred_start) <= now:
            raise LifeError("LIFE_PREDICTION_MUST_PRECEDE_TARGET", 422)
        cutoff = now if obj.get("input_cutoff_at") is None else instant(obj["input_cutoff_at"])
        if cutoff > now:
            raise LifeError("LIFE_PREDICTION_FUTURE_CUTOFF", 422)
        values: list[float] = []
        evidence = []
        for event_id in sample_ids:
            event = store.authorized_event(event_id, principal, settings.policies)
            seconds = duration(event)
            if (
                event.scope != target.scope
                or event.event_type != target.event_type
                or event.evidence_level == "inferred"
                or seconds is None
                or event.occurred_end is None
                or instant(event.occurred_end) > cutoff
                or instant(event.recorded_at) > cutoff
            ):
                raise LifeError("LIFE_PREDICTION_SAMPLE_INELIGIBLE", 422)
            values.append(seconds)
            evidence.append(
                {
                    "event_id": event.event_id,
                    "revision": event.revision,
                    "raw_hash": event.raw_hash,
                    "duration_seconds": seconds,
                    "occurred_end": event.occurred_end,
                    "recorded_at": event.recorded_at,
                }
            )
        adequate = len(values) >= settings.prediction_min_samples
        sorted_values = sorted(values)
        interval = (
            None
            if not adequate
            else [
                sorted_values[(len(values) - 1) // 4],
                sorted_values[(3 * (len(values) - 1)) // 4],
            ]
        )
        result = {
            "schema_version": 1,
            "prediction_id": prediction_id,
            "target_id": target_id,
            "target_revision": target.revision,
            "target_type": target.event_type,
            "scope": target.scope,
            "issued_at": stamp(now),
            "input_cutoff_at": stamp(cutoff),
            "target_start": target.occurred_start,
            "target_end": target.occurred_end,
            "status": "issued" if adequate else "insufficient_data",
            "estimator": "duration-median-v1",
            "personalized_model": False,
            "point_estimate": median(values) if adequate else None,
            "unit": "seconds",
            "interval": interval,
            "interval_kind": "empirical_middle_50_percent",
            "sample_count": len(values),
            "minimum_samples_setting": settings.prediction_min_samples,
            "evidence_snapshot": evidence,
            "caveat": "표본 개수 설정은 통계적 충분성이나 미래 정확도의 보증이 아닙니다.",
        }
        encoded = canonical(result)
        store.connection.execute(
            "INSERT INTO life_predictions VALUES(?,?,?,?,?,?,?,?)",
            (
                prediction_id,
                target_id,
                target.scope,
                stamp(now),
                stamp(cutoff),
                target.occurred_start,
                encoded,
                digest(encoded),
            ),
        )
        receipt = store._receipt(
            principal.client_id,
            key,
            request_digest,
            "prediction_issue",
            [(target.event_id, target.revision)],
            now,
        )
        store.bump()
        return {**result, "receipt_id": receipt, "replayed": False}


def record_actual(
    store: LifeStore, data: Mapping, settings: LifeSettings, principal: LifePrincipal, now: datetime
) -> dict:
    settings.require("prediction")
    if "predict" not in principal.operations:
        raise LifeError("LIFE_OPERATION_FORBIDDEN", 403)
    obj = object_fields(
        data,
        {"idempotency_key", "prediction_id", "expected_target_revision"},
        {"idempotency_key", "prediction_id", "expected_target_revision"},
    )
    key = identifier(obj["idempotency_key"])
    prediction_id = identifier(obj["prediction_id"])
    expected_revision = integer(obj["expected_target_revision"], minimum=1)
    request_digest = digest(canonical({"operation": "prediction_actual", **obj}))
    with store.transaction():
        original = authorized_prediction(store, prediction_id, principal, settings)
        replay = store._replay(principal.client_id, key, request_digest)
        if replay:
            # A repeated key maps to its original evaluation, not the latest actual.
            rows = store.connection.execute(
                "SELECT actual_json,content_digest FROM life_prediction_actuals WHERE prediction_id=? ORDER BY revision",
                (prediction_id,),
            ).fetchall()
            for encoded, checksum in rows:
                if digest(encoded) != checksum:
                    raise LifeError("LIFE_PREDICTION_INTEGRITY", 503)
                previous = strict_json(encoded)
                if previous["request_digest"] == request_digest:
                    return {**previous, "receipt_id": replay, "replayed": True}
            raise LifeError("LIFE_PREDICTION_ACTUAL_MISSING", 503)
        target = store.authorized_event(original["target_id"], principal, settings.policies)
        if target.revision != expected_revision:
            raise LifeError("LIFE_REVISION_CONFLICT", 409)
        actual = duration(target)
        state, reason = "scored", None
        if target.event_status == "cancelled":
            state, reason = "unscored", "target_cancelled"
        elif actual is None:
            state, reason = "unscored", "actual_unavailable"
        elif target.evidence_level == "inferred":
            state, reason = "unscored", "actual_inferred"
        elif target.occurred_end is not None and instant(target.occurred_end) > now:
            state, reason = "ineligible", "outcome_in_future"
        elif target.occurred_start is None or instant(target.occurred_start) <= instant(
            original["issued_at"]
        ):
            state, reason = "ineligible", "prediction_not_before_actual"
        elif original["point_estimate"] is None:
            state, reason = "unscored", "insufficient_prediction_inputs"
        for sample in original["evidence_snapshot"]:
            current = store.authorized_event(sample["event_id"], principal, settings.policies)
            if current.revision != sample["revision"] or current.raw_hash != sample["raw_hash"]:
                state, reason = "ineligible", "input_evidence_revised"
        prior = store.connection.execute(
            "SELECT MAX(revision) FROM life_prediction_actuals WHERE prediction_id=?",
            (prediction_id,),
        ).fetchone()[0]
        revision = 1 if prior is None else prior + 1
        result = {
            "prediction_id": prediction_id,
            "revision": revision,
            "target_id": target.event_id,
            "target_revision": target.revision,
            "target_evidence_id": target.evidence_id,
            "recorded_at": stamp(now),
            "actual": actual,
            "unit": "seconds",
            "evaluation_state": state,
            "reason": reason,
            "error_seconds": None if state != "scored" else actual - original["point_estimate"],
            "absolute_error_seconds": None
            if state != "scored"
            else abs(actual - original["point_estimate"]),
            "request_digest": request_digest,
        }
        encoded = canonical(result)
        store.connection.execute(
            "INSERT INTO life_prediction_actuals VALUES(?,?,?,?,?)",
            (prediction_id, revision, encoded, digest(encoded), stamp(now)),
        )
        receipt = store._receipt(
            principal.client_id,
            key,
            request_digest,
            "prediction_actual",
            [(target.event_id, target.revision)],
            now,
        )
        store.bump()
        return {**result, "receipt_id": receipt, "replayed": False}


def list_predictions(
    store: LifeStore | None, principal: LifePrincipal, settings: LifeSettings, *, limit: int = 100
) -> dict:
    integer(limit, minimum=1, maximum=200)
    if store is None:
        return {"predictions": [], "scored_count": 0, "mae_seconds": None}
    scopes = tuple(principal.scopes)
    if not scopes:
        return {"predictions": [], "scored_count": 0, "mae_seconds": None}
    rows = store.connection.execute(
        "SELECT prediction_id FROM life_predictions WHERE scope IN ("
        + ",".join("?" for _ in scopes)
        + ") ORDER BY issued_at DESC,prediction_id LIMIT ?",
        (*scopes, limit),
    ).fetchall()
    results, errors = [], []
    for row in rows:
        try:
            prediction = authorized_prediction(store, row[0], principal, settings)
        except LifeError as exc:
            if exc.status == 404:
                continue
            raise
        actual_row = store.connection.execute(
            "SELECT actual_json,content_digest FROM life_prediction_actuals WHERE prediction_id=? ORDER BY revision DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        actual = None
        if actual_row:
            if digest(actual_row[0]) != actual_row[1]:
                raise LifeError("LIFE_PREDICTION_INTEGRITY", 503)
            actual = strict_json(actual_row[0])
            current_target = store.current(prediction["target_id"])
            if current_target.revision != actual["target_revision"]:
                actual = {
                    **actual,
                    "evaluation_state": "stale",
                    "reason": "target_revised_after_evaluation",
                    "error_seconds": None,
                    "absolute_error_seconds": None,
                }
            if actual["evaluation_state"] == "scored":
                errors.append(actual["absolute_error_seconds"])
        # Snapshot values are only included for an authorized user; all inputs were checked above.
        results.append({**prediction, "actual_result": actual})
    return {
        "predictions": results,
        "scored_count": len(errors),
        "mae_seconds": sum(errors) / len(errors) if errors else None,
        "estimator": "duration-median-v1",
        "model_improvement_claimed": False,
        "window": "returned_authorized_predictions_only",
    }
