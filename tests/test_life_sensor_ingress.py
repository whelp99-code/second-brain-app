"""Sensor fixtures, actual HTTP ingress, deletion and disabled-policy guards."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sb.config import Config
from sb.effect_values import JsonObject
from sb.life_contracts import LifeInputError
from sb.life_sensors import health_batch, parse_overland, segments, sleep_union
from sb.pipeline import run_life_import
from sb.store.ledger import Ledger
from tests import test_web
from tests.life_test_support import (
    config_table,
    json_rows,
    json_text,
)
from tests.life_test_support import request as _request
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config


def point(at: datetime, latitude: float=37.5, longitude: float=127.0, accuracy: float=20) -> JsonObject:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "timestamp": at.isoformat(),
            "horizontal_accuracy": accuracy,
            "device_id": "fixture",
        },
    }


def sensor_config(tmp_path: Path) -> tuple[Config, Path]:
    cfg, root = life_config(tmp_path)
    cfg = replace(
        cfg,
        raw={
            **cfg.raw,
            "life": {
                **config_table(cfg.raw["life"]),
                "location_capture": True,
                "health_capture": True,
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "sensitivity": "restricted",
                        "external_processing": "local_only",
                        "allowed_types": [
                            "location_point",
                            "location_visit",
                            "location_trip",
                            "health_sample",
                        ],
                    }
                },
            },
            "life_sensor_sources": {
                "test-notes": {"health_types": ["sleep", "steps", "heart_rate", "hrv"]}
            },
        },
    )
    return cfg, root


def test_locations_accuracy_gaps_and_replay(tmp_path: Path) -> None:
    cfg, root = sensor_config(tmp_path)
    points = [
        point(NOW - timedelta(minutes=20)),
        point(NOW - timedelta(minutes=15)),
        point(NOW - timedelta(minutes=10), latitude=37.51),
        point(NOW - timedelta(minutes=5), latitude=37.52),
    ]
    document = {"locations": points}
    parsed = parse_overland(document, now=NOW)
    assert len(parsed) == 4 and len(segments(parsed)) >= 1
    low = parse_overland(
        {"locations": [point(NOW - timedelta(minutes=10), accuracy=-1), point(NOW, accuracy=500)]},
        now=NOW,
    )
    assert segments(low) == ()
    first, result = run_life_import(
        cfg, "test-notes", "overland", json.dumps(document).encode(), now=NOW
    )
    assert first.exit_code == 0, result
    assert len(json_rows(result["receipts"])) >= 4
    second, replay = run_life_import(
        cfg, "test-notes", "overland", json.dumps(document).encode(), now=NOW
    )
    assert second.exit_code == 0 and replay["import_receipt_id"] == result["import_receipt_id"]
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
        assert len(events) == len(json_rows(result["receipts"]))
        assert all(
            e.sensitivity == "restricted" and e.external_processing == "local_only" for e in events
        )


def test_health_absent_is_not_zero_and_sleep_dedup() -> None:
    sample = {
        "id": "sample1",
        "type": "steps",
        "start": NOW.isoformat(),
        "end": NOW.isoformat(),
        "value": 0,
        "unit": "count",
        "source": "fixture",
    }
    rows, _removed, anchor = health_batch(
        {"type": "steps", "samples": [sample], "anchor": "anchor1"},
        allowed_types=["steps"],
        timezone="UTC",
        now=NOW,
    )
    assert rows[0]["value"] == 0 and rows[0]["value_status"] == "observed" and anchor == "anchor1"
    rows, _, _ = health_batch(
        {"type": "steps", "samples": [{**sample, "value": None, "value_status": "unavailable"}]},
        allowed_types=["steps"],
        timezone="UTC",
        now=NOW,
    )
    assert rows[0]["value"] is None
    with pytest.raises(LifeInputError, match="TYPE_DISABLED"):
        _ = health_batch(
            {"type": "steps", "samples": [sample]}, allowed_types=["sleep"], timezone="UTC", now=NOW
        )
    sleep = [
        {
            "type": "sleep",
            "source": "watch",
            "sleep_stage": 3,
            "start": (NOW - timedelta(hours=2)).isoformat(),
            "end": NOW.isoformat(),
        },
        {
            "type": "sleep",
            "source": "watch",
            "sleep_stage": 3,
            "start": (NOW - timedelta(hours=1)).isoformat(),
            "end": NOW.isoformat(),
        },
    ]
    assert sleep_union(sleep)["combined_minutes"] == 120
    assert sleep_union(sleep + [{**sleep[0], "source": "other"}])["combined_minutes"] is None


def test_health_actual_http_delete_cursor_and_no_resurrection(tmp_path: Path) -> None:
    cfg, root = sensor_config(tmp_path)
    sample = {
        "id": "fixture-step",
        "type": "steps",
        "start": NOW.isoformat(),
        "end": NOW.isoformat(),
        "value": 7,
        "unit": "count",
        "source": "fixture",
    }
    with test_web._running(cfg) as base:
        code, result = _request(
            base + "/api/life/v1/health/test-notes",
            method="POST",
            payload={"type": "steps", "samples": [sample], "anchor": "v1"},
        )
        assert code == 202, result
        event_id = json_text(json_rows(result["receipts"])[0]["event_id"])
        code, evidence = _request(base + f"/api/life/v1/attachments/{event_id}/0")
        assert code == 200 and evidence["content_type"] == "application/json"
        code, result = _request(
            base + "/api/life/v1/health/test-notes",
            method="POST",
            payload={
                "type": "steps",
                "samples": [],
                "deleted": ["fixture-step", "unseen-sample"],
                "anchor": "v2",
            },
        )
        assert code == 202, result
        code, _missing = _request(base + f"/api/life/v1/attachments/{event_id}/0")
        assert code == 404
        code, replayed = _request(
            base + "/api/life/v1/health/test-notes",
            method="POST",
            payload={"type": "steps", "samples": [sample], "anchor": "v1"},
        )
        assert code == 202, replayed
        code, events = _request(base + "/api/life/v1/timeline?day=2026-09-26")
        assert code == 200 and json_rows(events["events"]) == []
    with Ledger(root) as ledger:
        assert ledger.life_store().events(scopes=("principal:owner",), now=NOW) == ()


def test_overland_success_shape_after_actual_publication(tmp_path: Path) -> None:
    cfg, _root = sensor_config(tmp_path)
    with test_web._running(cfg) as base:
        code, result = _request(
            base + "/api/life/v1/overland/test-notes",
            method="POST",
            payload={"locations": [point(NOW)]},
        )
        assert code == 200 and result["result"] == "ok" and result["state"] == "published"
        code, bad = _request(
            base + "/api/life/v1/overland/test-notes",
            method="POST",
            payload={"locations": [point(NOW, latitude=1000)]},
        )
        assert code != 200 and "result" not in bad


def test_disabled_health_collection_still_allows_deletions(tmp_path: Path) -> None:
    cfg, _root = sensor_config(tmp_path)
    sample = {
        "id": "fixture-step",
        "type": "steps",
        "start": NOW.isoformat(),
        "end": NOW.isoformat(),
        "value": 7,
        "unit": "count",
        "source": "fixture",
    }
    out, _ = run_life_import(
        cfg,
        "test-notes",
        "health",
        json.dumps({"type": "steps", "samples": [sample]}).encode(),
        now=NOW,
    )
    assert out.exit_code == 0
    off = replace(cfg, raw={**cfg.raw, "life": {**config_table(cfg.raw["life"]), "health_capture": False}})
    with pytest.raises(LifeInputError, match="DISABLED"):
        _ = run_life_import(
            off,
            "test-notes",
            "health",
            json.dumps({"type": "steps", "samples": [sample]}).encode(),
            now=NOW,
        )
    out, _ = run_life_import(
        off,
        "test-notes",
        "health",
        json.dumps({"type": "steps", "deleted": ["fixture-step"]}).encode(),
        now=NOW,
    )
    assert out.exit_code == 0
