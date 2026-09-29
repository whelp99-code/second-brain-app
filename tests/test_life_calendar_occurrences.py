"""Calendar occurrence identity: one instance is not the series."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sb.life_contracts import LifeInputError
from sb.life_exports import parse_export
from sb.pipeline import run_ingest
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config

FIXTURES = Path(__file__).parent / "fixtures" / "life-exports"


def _config(tmp_path: Path, source: Path):
    config, root = life_config(tmp_path)
    return replace(
        config,
        raw={
            **config.raw,
            "sources": [
                {
                    "id": "test-notes",
                    "adapter": "life-records",
                    "root": str(source),
                    "format": "google-calendar",
                }
            ],
        },
    ), root


def test_instance_cancel_does_not_cancel_series_or_other_instances(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    document = json.loads((FIXTURES / "google-instances.json").read_text(encoding="utf-8"))
    path = source / "calendar.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    config, root = _config(tmp_path, source)
    assert run_ingest(config, sources=["test-notes"]).errors == 0
    document["items"][1]["status"] = "cancelled"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert run_ingest(config, sources=["test-notes"]).errors == 0
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
    by_item = {event.source_item_id: event for event in events}
    assert len(by_item) == 2
    assert all(not item_id.startswith("gcal:weekly") for item_id in by_item)
    cancelled = [event for event in events if event.event_status == "cancelled"]
    planned = [event for event in events if event.event_status == "planned"]
    assert len(cancelled) == 1 and len(planned) == 1
    assert planned[0].revision == 1 and cancelled[0].revision == 2


def test_series_master_still_rejected_expansion_required() -> None:
    with pytest.raises(LifeInputError, match="EXPANSION_REQUIRED"):
        parse_export(
            "google-calendar",
            json.dumps({"items": [{"id": "x", "recurrence": ["RRULE:FREQ=DAILY"]}]}).encode(),
            "calendar.json",
        )
    with pytest.raises(LifeInputError, match="EXPANSION_REQUIRED"):
        parse_export("graph-calendar", (FIXTURES / "graph-series-master.json").read_bytes(), "calendar.json")


def test_date_only_event_keeps_day_precision() -> None:
    event = parse_export(
        "google-calendar", (FIXTURES / "google-date-only.json").read_bytes(), "calendar.json"
    )[0]
    assert event["time_precision"] == "day"
    local = datetime.fromisoformat(str(event["occurred_start"])).astimezone(ZoneInfo("Asia/Seoul"))
    assert local.date().isoformat() == "2026-09-25"
    assert local.hour == 0 and local.minute == 0


def test_rescheduled_instance_is_new_revision_same_event_id(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    document = json.loads((FIXTURES / "google-instances.json").read_text(encoding="utf-8"))
    document["items"] = [document["items"][0]]
    path = source / "calendar.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    config, root = _config(tmp_path, source)
    assert run_ingest(config, sources=["test-notes"]).errors == 0
    document["items"][0]["start"]["dateTime"] = "2026-09-24T11:30:00+09:00"
    document["items"][0]["end"]["dateTime"] = "2026-09-24T12:30:00+09:00"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert run_ingest(config, sources=["test-notes"]).errors == 0
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
    assert len(events) == 1
    assert events[0].revision == 2
    assert events[0].source_item_id.startswith("gcal-instance:")
    assert events[0].occurred_start == "2026-09-24T02:30:00+00:00"
