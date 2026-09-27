"""Phone History encrypted repository -> actual local Second Brain HTTP intake."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sb.life_config import parse_settings
from sb.life_store import read_life_store
from sb.runtime_access import read_root
from tests.test_life_http import TOKEN, request
from tests.test_life_pipeline import life_config
from tests.test_web import _running


@pytest.fixture
def phone_system(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "phone-history" / "server"))
    monkeypatch.delenv("SB_WEB_TOKEN", raising=False)
    monkeypatch.setenv("SB_LIFE_TEST_DEVICE", TOKEN)
    from phone_history.config import Settings
    from phone_history.service import PhoneHistoryService

    config, root, principal = life_config(tmp_path)
    with _running(config) as base:
        settings = Settings(
            data_dir=tmp_path / "phone-data",
            api_token="synthetic-phone-server-" + "a" * 32,
            master_key=bytes(range(32)),
            second_brain_base_url=base,
            second_brain_sink_mode="life-http",
            second_brain_token_env="SB_LIFE_TEST_DEVICE",
            second_brain_life_source_id="phone",
        )
        service = PhoneHistoryService(settings)
        yield config, root, principal, base, service


def batch(event_type="quick_note", body="Shared synthetic memory"):
    from phone_history.models import parse_batch

    return parse_batch(
        {
            "schema_version": 1,
            "device_id": "synthetic-iphone",
            "events": [
                {
                    "schema_version": 1,
                    "id": "phevt:synthetic:1",
                    "occurred_at": "2026-09-26T12:00:00+09:00",
                    "source": "manual",
                    "event_type": event_type,
                    "capture_mode": "explicit",
                    "title": "공유한 메모",
                    "body": body,
                    "url": None,
                    "project_hint": None,
                    "sensitivity": "personal",
                    "attachment": None,
                }
            ],
        }
    )


def test_phone_capture_reaches_durable_life_intake_without_auto_run(phone_system):
    config, _, principal, base, service = phone_system
    response = service.ingest(batch(), idempotency_key="phone-batch-0001")
    assert response.status == 201
    event = service.repository.get_event("phevt:synthetic:1")
    assert event.sink_state == "exported"
    reference = json.loads(event.sink_ref)
    assert reference["intake_only"] and reference["canonical"] is False
    assert reference["searchable"] is False and reference["projected"] is False
    with read_root(config) as root, read_life_store(root) as store:
        records = store.events(principal, parse_settings(config.raw).policies)
        assert len(records) == 1 and "Shared synthetic memory" in records[0].body
        assert store.pending(principal, parse_settings(config.raw).policies)
    result = request(base, "/api/life/v1/run", body={})
    assert result[0] == 200 and result[1]["processed"] == 1
    status, view = request(base, "/api/life/v1/views/obsidian/manifest")
    assert status == 200 and "Shared synthetic memory" in json.dumps(view, ensure_ascii=False)


def test_sink_retry_after_lost_acceptance_response_keeps_one_event(phone_system, monkeypatch):
    config, _, principal, _, service = phone_system
    from phone_history.life_sink import LifeInboxSink
    from phone_history.sink import SinkError

    original = LifeInboxSink._request
    dropped = []

    def once(self, path, body=None):
        result = original(self, path, body)
        if path == "/events:batch" and not dropped:
            dropped.append(True)
            raise SinkError("synthetic_response_lost")
        return result

    monkeypatch.setattr(LifeInboxSink, "_request", once)
    service.ingest(batch(), idempotency_key="phone-batch-0001")
    event = service.repository.get_event("phevt:synthetic:1")
    assert event.sink_state == "pending"
    # Use the existing pending export retry method, not a fabricated success marker.
    service._export(event)
    assert service.repository.get_event(event.id).sink_state == "exported"
    with read_root(config) as root, read_life_store(root) as store:
        assert len(store.events(principal, parse_settings(config.raw).policies)) == 1
        assert (
            store.connection.execute(
                "SELECT count(*) FROM life_receipts WHERE operation='capture'"
            ).fetchone()[0]
            == 1
        )


def test_source_retraction_removes_published_memory_and_is_idempotent(phone_system):
    config, _, principal, base, service = phone_system
    service.ingest(batch(), idempotency_key="phone-batch-0001")
    event = service.repository.get_event("phevt:synthetic:1")
    upload = json.loads(event.sink_ref)["upload_id"]
    assert request(base, "/api/life/v1/run", body={})[0] == 200
    first = json.loads(service.sink.retract(upload))
    again = json.loads(service.sink.retract(upload))
    assert first["receipt_id"] == again["receipt_id"] and first["deleted"]
    with read_root(config) as root, read_life_store(root) as store:
        assert store.events(principal, parse_settings(config.raw).policies) == ()
    _, view = request(base, "/api/life/v1/views/obsidian/manifest")
    assert "Shared synthetic memory" not in json.dumps(view, ensure_ascii=False)


def test_source_retraction_after_user_revision_retracts_same_origin(phone_system):
    _, _, _, base, service = phone_system
    service.ingest(batch(), idempotency_key="phone-batch-0001")
    event = service.repository.get_event("phevt:synthetic:1")
    reference = json.loads(event.sink_ref)
    assert (
        request(
            base,
            "/api/life/v1/corrections",
            body={
                "idempotency_key": "manual-correct",
                "event_id": reference["event_id"],
                "expected_revision": 1,
                "reason": "clarified source",
                "changes": {"body": "revised source"},
            },
        )[0]
        == 202
    )
    result = json.loads(service.sink.retract(reference["upload_id"]))
    assert result["deleted"]
    assert request(base, "/api/life/v1/events/" + reference["event_id"])[0] == 404


def test_unconfigured_or_unauthorized_sink_does_not_mark_success(phone_system, monkeypatch):
    _, _, _, _, service = phone_system
    monkeypatch.delenv("SB_LIFE_TEST_DEVICE")
    response = service.ingest(batch(), idempotency_key="phone-batch-0001")
    assert response.payload["events"][0]["sink_state"] == "pending"
    event = service.repository.get_event("phevt:synthetic:1")
    assert event.sink_ref is None


def test_legacy_sink_remains_default(phone_system):
    _, _, _, _, service = phone_system
    from phone_history.service import PhoneHistoryService
    from phone_history.sink import DisabledSink

    settings = replace(service.settings, second_brain_sink_mode="inbox", second_brain_vault=None)
    legacy = PhoneHistoryService(settings, repository=service.repository)
    assert isinstance(legacy.sink, DisabledSink)
    assert legacy.capabilities()["memory"]["auto_pipeline_run"] is False


def test_sink_only_accepts_https_or_loopback_and_rejects_admin_token_env(phone_system):
    from phone_history.life_sink import LifeInboxSink
    from phone_history.sink import SinkError

    with pytest.raises(SinkError, match="life_endpoint_invalid"):
        LifeInboxSink("http://example.com", "phone", "SB_LIFE_DEVICE")
    with pytest.raises(SinkError, match="life_device_token_required"):
        LifeInboxSink("https://example.com", "phone", "SB_WEB_TOKEN")
