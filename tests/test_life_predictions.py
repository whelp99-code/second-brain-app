"""Temporal prediction contracts using real SQLite and synthetic activity facts."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from sb.life_config import parse_settings
from sb.life_contracts import LifeError, canonical, digest, event_input, parse_event, stamp
from sb.life_predictions import issue, list_predictions, record_actual
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW, POLICY, payload, settings_raw
from tests.test_life_store import accept


@pytest.fixture
def prediction_store(tmp_path):
    raw = settings_raw()
    raw["life"]["prediction_min_samples"] = 2
    settings = parse_settings(raw)
    principal = settings.owner()
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        samples = []
        for index, minutes in enumerate([20, 30, 40]):
            start = NOW - timedelta(days=index + 1)
            event = parse_event(
                payload(
                    source_item_id=f"sample:{index}",
                    event_type="activity",
                    event_status="occurred",
                    occurred_start=stamp(start),
                    occurred_end=stamp(start + timedelta(minutes=minutes)),
                ),
                POLICY,
                NOW,
            )
            accept(store, event, key=f"sample:{index}")
            samples.append(event)
        target = parse_event(
            payload(
                source_item_id="target",
                event_type="activity",
                event_status="planned",
                occurred_start=stamp(NOW + timedelta(hours=1)),
                occurred_end=stamp(NOW + timedelta(hours=2)),
            ),
            POLICY,
            NOW,
        )
        accept(store, target, key="target")
        yield store, settings, principal, samples, target


def prediction_request(samples, target, key="forecast:1"):
    return {
        "idempotency_key": key,
        "target_id": target.event_id,
        "sample_event_ids": [sample.event_id for sample in samples],
    }


def actual_target(store, target, *, status="occurred", minutes=35, key="actual:source"):
    now = NOW + timedelta(hours=3)
    data = {
        **event_input(target),
        "source_version": key,
        "event_status": status,
        "occurred_end": stamp(NOW + timedelta(hours=1, minutes=minutes)),
        "evidence_level": "user_asserted",
    }
    changed = parse_event(data, POLICY, now, revision=target.revision + 1)
    store.correct(
        changed,
        client_id="local-owner",
        key=key,
        request_digest=digest(canonical(data)),
        expected_revision=target.revision,
        now=now,
    )
    return changed, now


def test_predict_before_result_and_score_exact_target(prediction_store):
    store, settings, principal, samples, target = prediction_store
    result = issue(store, prediction_request(samples, target), settings, principal, NOW)
    assert result["point_estimate"] == 1800
    assert result["personalized_model"] is False
    assert result["sample_count"] == 3
    original = store.connection.execute("SELECT prediction_json FROM life_predictions").fetchone()[
        0
    ]
    actual, now = actual_target(store, target)
    scored = record_actual(
        store,
        {
            "idempotency_key": "score:1",
            "prediction_id": result["prediction_id"],
            "expected_target_revision": actual.revision,
        },
        settings,
        principal,
        now,
    )
    assert scored["actual"] == 2100 and scored["error_seconds"] == 300
    assert scored["evaluation_state"] == "scored"
    assert (
        store.connection.execute("SELECT prediction_json FROM life_predictions").fetchone()[0]
        == original
    )
    report = list_predictions(store, principal, settings)
    assert report["scored_count"] == 1 and report["mae_seconds"] == 300
    assert report["model_improvement_claimed"] is False


def test_identical_prediction_request_replays_and_changed_key_payload_conflicts(prediction_store):
    store, settings, principal, samples, target = prediction_store
    req = prediction_request(samples, target)
    first = issue(store, req, settings, principal, NOW)
    again = issue(store, req, settings, principal, NOW + timedelta(minutes=1))
    assert first["prediction_id"] == again["prediction_id"] and again["replayed"]
    assert first["issued_at"] == again["issued_at"]
    with pytest.raises(LifeError, match="LIFE_IDEMPOTENCY_CONFLICT"):
        issue(store, {**req, "sample_event_ids": []}, settings, principal, NOW)


def test_cannot_issue_after_target_or_backdate_server_issue_time(prediction_store):
    store, settings, principal, samples, target = prediction_store
    req = prediction_request(samples, target)
    with pytest.raises(LifeError, match="LIFE_PREDICTION_MUST_PRECEDE_TARGET"):
        issue(store, req, settings, principal, NOW + timedelta(hours=2))
    with pytest.raises(LifeError, match="LIFE_FIELDS_INVALID"):
        issue(store, {**req, "issued_at": stamp(NOW - timedelta(days=1))}, settings, principal, NOW)
    with pytest.raises(LifeError, match="LIFE_PREDICTION_FUTURE_CUTOFF"):
        issue(
            store,
            {**req, "input_cutoff_at": stamp(NOW + timedelta(seconds=1))},
            settings,
            principal,
            NOW,
        )


def test_future_recorded_sample_cannot_leak_into_cutoff(prediction_store):
    store, settings, principal, samples, target = prediction_store
    req = prediction_request(samples, target)
    with pytest.raises(LifeError, match="LIFE_PREDICTION_SAMPLE_INELIGIBLE"):
        issue(
            store,
            {**req, "input_cutoff_at": stamp(NOW - timedelta(seconds=1))},
            settings,
            principal,
            NOW,
        )


def test_too_few_samples_and_missing_actual_are_not_zero_error(prediction_store):
    store, settings, principal, samples, target = prediction_store
    result = issue(store, prediction_request(samples[:1], target), settings, principal, NOW)
    assert result["status"] == "insufficient_data" and result["point_estimate"] is None
    actual = record_actual(
        store,
        {
            "idempotency_key": "score:missing",
            "prediction_id": result["prediction_id"],
            "expected_target_revision": 1,
        },
        settings,
        principal,
        NOW + timedelta(hours=3),
    )
    assert actual["evaluation_state"] == "unscored"
    assert actual["actual"] is None and actual["error_seconds"] is None


def test_cancelled_target_is_unscored(prediction_store):
    store, settings, principal, samples, target = prediction_store
    result = issue(store, prediction_request(samples, target), settings, principal, NOW)
    changed, now = actual_target(store, target, status="cancelled")
    score = record_actual(
        store,
        {
            "idempotency_key": "score:cancel",
            "prediction_id": result["prediction_id"],
            "expected_target_revision": changed.revision,
        },
        settings,
        principal,
        now,
    )
    assert score["evaluation_state"] == "unscored" and score["reason"] == "target_cancelled"


def test_actual_revision_appends_and_retry_keeps_original_score(prediction_store):
    store, settings, principal, samples, target = prediction_store
    prediction = issue(store, prediction_request(samples, target), settings, principal, NOW)
    changed, now = actual_target(store, target, minutes=35)
    req = {
        "idempotency_key": "score:1",
        "prediction_id": prediction["prediction_id"],
        "expected_target_revision": 2,
    }
    first = record_actual(store, req, settings, principal, now)
    revised, now = actual_target(store, changed, minutes=40, key="actual:corrected")
    stale = list_predictions(store, principal, settings)["predictions"][0]["actual_result"]
    assert stale["evaluation_state"] == "stale" and stale["error_seconds"] is None
    second = record_actual(
        store,
        {**req, "idempotency_key": "score:2", "expected_target_revision": revised.revision},
        settings,
        principal,
        now,
    )
    assert second["revision"] == 2 and second["actual"] == 2400
    replay = record_actual(store, req, settings, principal, now)
    assert (
        replay["revision"] == first["revision"]
        and replay["actual"] == first["actual"]
        and replay["replayed"]
    )


def test_prediction_and_actual_sql_updates_are_rejected(prediction_store):
    store, settings, principal, samples, target = prediction_store
    result = issue(store, prediction_request(samples, target), settings, principal, NOW)
    actual, now = actual_target(store, target)
    record_actual(
        store,
        {
            "idempotency_key": "score:1",
            "prediction_id": result["prediction_id"],
            "expected_target_revision": actual.revision,
        },
        settings,
        principal,
        now,
    )
    with (
        pytest.raises(sqlite3.IntegrityError, match="life_prediction_immutable"),
        store.transaction(),
    ):
        store.connection.execute("UPDATE life_predictions SET issued_at='2000-01-01'")
    with pytest.raises(sqlite3.IntegrityError, match="life_actual_immutable"), store.transaction():
        store.connection.execute("UPDATE life_prediction_actuals SET actual_json='{}'")


def test_deleted_input_revokes_prediction_and_metrics(prediction_store):
    store, settings, principal, samples, target = prediction_store
    issue(store, prediction_request(samples, target), settings, principal, NOW)
    store.forget(
        samples[0].event_id,
        client_id="local-owner",
        key="delete-input",
        request_digest=digest("delete-input"),
        expected_revision=1,
        reason_hash=digest("remove source"),
        now=NOW,
    )
    assert list_predictions(store, principal, settings)["predictions"] == []
    assert list_predictions(store, principal, settings)["mae_seconds"] is None


def test_wrong_scope_or_no_predict_permission_cannot_issue(prediction_store):
    store, settings, principal, samples, target = prediction_store
    with pytest.raises(LifeError, match="LIFE_OPERATION_FORBIDDEN"):
        issue(
            store,
            prediction_request(samples, target),
            settings,
            replace(principal, operations=("read",)),
            NOW,
        )
    hidden = replace(principal, scopes=("other-scope",))
    with pytest.raises(LifeError, match="LIFE_EVENT_NOT_FOUND"):
        issue(store, prediction_request(samples, target), settings, hidden, NOW)


def test_input_revision_after_issue_marks_score_ineligible(prediction_store):
    store, settings, principal, samples, target = prediction_store
    prediction = issue(store, prediction_request(samples, target), settings, principal, NOW)
    sample = samples[0]
    modified = parse_event(
        {
            **event_input(sample),
            "source_version": "corrected-training-data",
            "body": "new evidence",
        },
        POLICY,
        NOW + timedelta(minutes=10),
        revision=2,
    )
    store.correct(
        modified,
        client_id="local-owner",
        key="correct-input",
        request_digest=digest("correct-input"),
        expected_revision=1,
        now=NOW + timedelta(minutes=10),
    )
    actual, now = actual_target(store, target)
    score = record_actual(
        store,
        {
            "idempotency_key": "score:changed-input",
            "prediction_id": prediction["prediction_id"],
            "expected_target_revision": actual.revision,
        },
        settings,
        principal,
        now,
    )
    assert score["evaluation_state"] == "ineligible" and score["reason"] == "input_evidence_revised"
