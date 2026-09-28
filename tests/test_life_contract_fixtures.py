"""Frozen life-event contract examples. Stdlib validator only; no jsonschema."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.life_contracts import (
    LifeInputError,
    SourcePolicyV1,
    life_record_link,
    validate_life_document,
)
from sb.life_values import parse_event
from sb.memory_records import parse_page_records

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "life-contract"
SCHEMA_PATH = ROOT / "contracts" / "life-event-v1.json"
RECORDED = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
OLD_CONSUMER_SHA256 = "42d4a715a2c1815b5fb04bc2b3f05f88e4a71de543ab65c7e099f98a06188bd3"

POLICY = SourcePolicyV1(
    source_id="notes-personal",
    scopes=("owner:life",),
    enabled=True,
    allowed_types=("note_saved", "calendar_event"),
    sensitivity="personal",
    external_processing="local_only",
    retention_days=365,
    policy_revision="v1",
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _inputs() -> dict[str, tuple[dict, int]]:
    return {
        "event-v1-minimal.json": (
            {
                "source_item_id": "item-minimal",
                "source_version": "v1",
                "event_type": "note_saved",
                "title": "짧은 메모",
                "body": "",
                "occurred_start": None,
                "time_precision": "unknown",
                "timezone": "Asia/Seoul",
            },
            1,
        ),
        "event-v1-full.json": (
            {
                "source_item_id": "item-full",
                "source_version": "v3",
                "event_type": "calendar_event",
                "title": "여행 중 회의",
                "body": "파리 도착 후 일정",
                "event_status": "planned",
                "evidence_level": "observed",
                "review_state": "confirmed",
                "occurred_start": "2026-06-15T09:00:00+02:00",
                "occurred_end": "2026-06-15T10:00:00+02:00",
                "observed_at": "2026-06-15T09:05:00+02:00",
                "timezone": "Europe/Paris",
                "time_precision": "minute",
                "valid_from": "2026-06-01T00:00:00+02:00",
                "valid_until": "2026-06-30T00:00:00+02:00",
                "entities": [{"entity_id": "person:ada", "kind": "person", "label": "Ada"}],
                "value": 2,
                "value_status": "observed",
                "unit": "count",
                "confidence": 0.5,
                "change_reason": "owner correction",
            },
            2,
        ),
    }


def test_schema_sidecar_digest_matches_file():
    raw = SCHEMA_PATH.read_bytes()
    sidecar = Path(str(SCHEMA_PATH) + ".sha256").read_text(encoding="utf-8")
    assert sidecar == hashlib.sha256(raw).hexdigest() + "\n"
    assert len(sidecar) == 65


def test_examples_roundtrip_through_parse_event_unchanged():
    schema = _schema()
    for name, (payload, revision) in _inputs().items():
        document = _load(name)
        validate_life_document(document, schema)
        event = parse_event(payload, POLICY, recorded_at=RECORDED, revision=revision)
        assert event.as_dict() == document


def test_old_consumer_fixture_bytes_are_unchanged():
    raw = (FIXTURES / "old-consumer-request-v1.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OLD_CONSUMER_SHA256
    request = json.loads(raw)
    assert request["operation"] == "remember"
    assert request["schema_version"] == 1
    assert "event_id" not in request
    assert "event_status" not in request
    with pytest.raises(LifeInputError):
        validate_life_document(request, _schema())


def test_memory_record_digests_not_rehashed_by_life_link():
    raw = (
        b"---\n"
        b"sensitivity: personal\n"
        b"valid_from: 2026-09-01T00:00:00.000Z\n"
        b"valid_until: 2026-09-02T00:00:00.000Z\n"
        b"---\n"
        b"Alpha fact [^a8920f4d]\n"
        b"[^a8920f4d]: wiki/source\n"
    )
    record = parse_page_records(raw, "wiki/page")[0]
    before = record.record_digest
    event_id = _load("event-v1-minimal.json")["event_id"]
    link = life_record_link(
        record_id=record.record_id,
        record_digest=record.record_digest,
        event_id=event_id,
        revision=1,
    )
    assert record.record_digest == before
    assert link["record_digest"] == before
    assert "record_text" not in link
    other = life_record_link(
        record_id=record.record_id,
        record_digest=record.record_digest,
        event_id=event_id,
        revision=2,
    )
    assert other["record_digest"] == before
    assert other["event_revision"] != link["event_revision"]


def test_schema_is_stdlib_validatable():
    source = (ROOT / "sb" / "life_contracts.py").read_text(encoding="utf-8")
    assert "import jsonschema" not in source
    assert "from jsonschema" not in source
    schema = _schema()
    validate_life_document(_load("event-v1-minimal.json"), schema)
    validate_life_document(_load("event-v1-full.json"), schema)
    validate_life_document(_load("receipt-v1.json"), schema, definition="receipt")
    validate_life_document(_load("relation-v1.json"), schema, definition="relation")
    validate_life_document(_load("policy-v1.json"), schema, definition="policy")
    broken = dict(_load("event-v1-minimal.json"))
    broken["event_status"] = "done"
    with pytest.raises(LifeInputError):
        validate_life_document(broken, schema)
    extra = dict(_load("receipt-v1.json"))
    extra["secret"] = "nope"
    with pytest.raises(LifeInputError):
        validate_life_document(extra, schema, definition="receipt")
