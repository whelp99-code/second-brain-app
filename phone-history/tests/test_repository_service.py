from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from phone_history.config import Settings
from phone_history.crypto import SecretBox
from phone_history.errors import ConflictError, CryptoError, NotFoundError
from phone_history.repository import Repository
from phone_history.service import PhoneHistoryService
from phone_history.sink import SinkError

from tests.conftest import batch_from, event_dict


class RecordingSink:
    def __init__(self, *, fail: bool = False, retract_error: str | None = None) -> None:
        self.fail = fail
        self.retract_error = retract_error
        self.calls: list[str] = []
        self.retracts: list[str] = []

    def export(self, event: object) -> str:
        event_id = event.id
        self.calls.append(event_id)
        if self.fail:
            raise SinkError("synthetic_sink_failure")
        return json.dumps(
            {"inbox_path": f"inbox/uploads/{event_id}.md", "upload_id": event_id},
            sort_keys=True,
        )

    def retract(self, upload_id: str) -> str:
        self.retracts.append(upload_id)
        if self.retract_error is not None:
            raise SinkError(self.retract_error)
        if self.fail:
            raise SinkError("synthetic_sink_failure")
        return json.dumps({"deleted": True, "upload_id": upload_id}, sort_keys=True)


def _candidate(title: str, content: str) -> dict[str, object]:
    return {
        "title": title,
        "content": content,
        "project_hint": "phone-history",
        "risk_flags": [],
        "redaction_count": 0,
        "knowledge_status": "UNVERIFIED",
        "approval_status": "UNREVIEWED",
        "canonical": False,
    }


def test_repository_encrypts_sensitive_fields_and_attachment(settings: object) -> None:
    repository = Repository(settings)
    title = "ULTRA_PRIVATE_TITLE_69de91"
    body = "ULTRA_PRIVATE_BODY_9471ab"
    attachment = b"ULTRA_PRIVATE_ATTACHMENT_4d72c1"
    event = batch_from(
        event_dict(
            event_id="phevt:encrypted:001",
            title=title,
            body=body,
            attachment=attachment,
        )
    ).events[0]
    result = repository.ingest_event(
        "iphone-secure-1",
        event,
        candidate_payload=_candidate(title, body),
    )
    assert result.state == "accepted"
    assert result.event.title == title
    assert result.event.body == body
    assert result.event.attachment is not None

    stored_bytes = b"".join(
        path.read_bytes() for path in settings.data_dir.rglob("*") if path.is_file()
    )
    assert title.encode() not in stored_bytes
    assert body.encode() not in stored_bytes
    assert attachment not in stored_bytes
    assert b"owner_review_required" not in stored_bytes


def test_repository_detects_tampered_event_ciphertext(settings: object) -> None:
    repository = Repository(settings)
    event = batch_from(event_dict(event_id="phevt:tamper:001")).events[0]
    repository.ingest_event("iphone-1", event, candidate_payload=None)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE events SET payload_enc = ? WHERE id = ?",
            (b"PH1" + b"0" * 40, event.id),
        )
    with pytest.raises(CryptoError, match="authentication failed"):
        repository.get_event(event.id)


def test_repository_rejects_same_event_id_with_changed_content(settings: object) -> None:
    repository = Repository(settings)
    first = batch_from(event_dict(event_id="phevt:collision:001", body="first")).events[0]
    second = batch_from(event_dict(event_id="phevt:collision:001", body="second")).events[0]
    repository.ingest_event("iphone-1", first, candidate_payload=None)
    same = repository.ingest_event("iphone-1", first, candidate_payload=None)
    assert same.state == "already_present"
    with pytest.raises(ConflictError, match="different content"):
        repository.ingest_event("iphone-1", second, candidate_payload=None)
    with pytest.raises(ConflictError, match="different content"):
        repository.ingest_event("iphone-2", first, candidate_payload=None)


def test_service_idempotency_and_event_conflict(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    batch = batch_from(event_dict(event_id="phevt:idempotency:001"))
    first = service.ingest(batch, idempotency_key="request-idem-0001")
    assert first.status == 201
    assert first.payload["accepted"] == 1
    assert first.payload["canonicalized"] == 0
    assert sink.calls == ["phevt:idempotency:001"]

    replay = service.ingest(batch, idempotency_key="request-idem-0001")
    assert replay.status == 200
    assert replay.payload["replayed"] is True
    assert sink.calls == ["phevt:idempotency:001"]

    changed = batch_from(event_dict(event_id="phevt:idempotency:002", body="changed"))
    with pytest.raises(ConflictError, match="different request"):
        service.ingest(changed, idempotency_key="request-idem-0001")


def test_service_sink_failure_stays_pending_and_maintenance_recovers(settings: object) -> None:
    sink = RecordingSink(fail=True)
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:pending:001"
    response = service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-pending-0001",
    )
    assert response.payload["events"][0]["sink_state"] == "pending"
    assert service.status()["pending_second_brain"] == 1

    sink.fail = False
    recovered = service.maintenance()
    assert recovered["second_brain"] == {"exported": 1, "pending": 0}
    assert service.status()["pending_second_brain"] == 0
    assert service.repository.get_event(event_id).sink_state == "exported"


def test_candidates_are_noncanonical_and_decision_has_no_approval_effect(settings: object) -> None:
    service = PhoneHistoryService(settings, sink=RecordingSink())
    service.ingest(
        batch_from(event_dict(event_id="phevt:candidate:001", title="Candidate")),
        idempotency_key="request-candidate-0001",
    )
    candidates = service.candidates()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["state"] == "unreviewed"
    assert candidate["canonical"] is False

    queued = service.decide_candidate(candidate["id"], "queue_for_owner_review")
    assert queued["state"] == "queued_for_owner_review"
    assert queued["canonical"] is False
    assert queued["approval_effect"] == "none"

    dismissed = service.decide_candidate(candidate["id"], "dismiss")
    assert dismissed["state"] == "dismissed"
    assert dismissed["canonical"] is False


def test_delete_erases_content_attachment_candidate_and_is_idempotent(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:delete:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id, attachment=b"delete me")),
        idempotency_key="request-delete-0001",
    )
    assert service.status()["events"] == 1
    assert service.status()["attachments"] == 1
    assert service.status()["unreviewed_candidates"] == 1

    deleted = service.delete_event(event_id, reason="owner_requested")
    assert deleted["state"] == "deleted"
    assert sink.retracts == [event_id]
    assert deleted["canonical_effect"] == "none"
    status = service.status()
    assert status["events"] == 0
    assert status["attachments"] == 0
    assert status["unreviewed_candidates"] == 0
    assert status["tombstones"] == 1
    assert not any(settings.attachment_dir.rglob("*.blob"))

    repeated = service.delete_event(event_id, reason="owner_requested")
    assert repeated["state"] == "already_deleted"
    original = batch_from(event_dict(event_id=event_id, attachment=b"delete me")).events[0]
    with pytest.raises(ConflictError, match="cannot be re-ingested"):
        service.repository.ingest_event("iphone-test-1", original, candidate_payload=None)


def test_delete_keeps_event_when_second_brain_retract_fails(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:delete-pending:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-delete-pending-0001",
    )
    sink.fail = True
    result = service.delete_event(event_id, reason="owner_requested")
    assert result["state"] == "pending"
    assert result["second_brain_retract"] == "synthetic_sink_failure"
    assert sink.retracts == [event_id]
    assert service.status()["events"] == 1
    assert service.repository.get_event(event_id).sink_state == "pending"


def test_delete_stays_pending_on_retract_not_found(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:delete-404:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-delete-404-0001",
    )
    sink.retract_error = "not_found"
    result = service.delete_event(event_id, reason="owner_requested")
    assert result["state"] == "pending"
    assert result["second_brain_retract"] == "not_found"
    assert service.status()["events"] == 1


def test_delete_stays_pending_on_retract_receipt_delay(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:delete-delay:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-delete-delay-0001",
    )
    sink.retract_error = "retract_receipt_pending"
    result = service.delete_event(event_id, reason="owner_requested")
    assert result["state"] == "pending"
    assert result["second_brain_retract"] == "retract_receipt_pending"
    assert service.status()["events"] == 1


def test_maintenance_retries_failed_retract_then_deletes(settings: object) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:retract-retry:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-retract-retry-0001",
    )
    export_calls = list(sink.calls)
    sink.fail = True
    failed = service.delete_event(event_id, reason="owner_requested")
    assert failed["state"] == "pending"
    assert sink.retracts == [event_id]

    sink.fail = False
    recovered = service.maintenance()
    assert recovered["second_brain"]["pending"] == 0
    assert sink.retracts == [event_id, event_id]
    assert sink.calls == export_calls
    with pytest.raises(NotFoundError):
        service.repository.get_event(event_id)
    assert service.status()["events"] == 0


def test_maintenance_keeps_retract_not_found_pending_without_reexport(
    settings: object,
) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:retract-retry-404:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-retract-retry-404-0001",
    )
    export_calls = list(sink.calls)
    sink.retract_error = "not_found"
    failed = service.delete_event(event_id, reason="owner_requested")
    assert failed["state"] == "pending"

    recovered = service.maintenance()
    assert recovered["second_brain"]["pending"] == 1
    assert recovered["second_brain"]["exported"] == 0
    assert sink.retracts == [event_id, event_id]
    assert sink.calls == export_calls
    assert service.repository.get_event(event_id).sink_state == "pending"


def test_maintenance_keeps_retract_receipt_delay_pending_without_reexport(
    settings: object,
) -> None:
    sink = RecordingSink()
    service = PhoneHistoryService(settings, sink=sink)
    event_id = "phevt:retract-retry-delay:001"
    service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-retract-retry-delay-0001",
    )
    export_calls = list(sink.calls)
    sink.retract_error = "retract_receipt_pending"
    failed = service.delete_event(event_id, reason="owner_requested")
    assert failed["state"] == "pending"

    recovered = service.maintenance()
    assert recovered["second_brain"]["pending"] == 1
    assert recovered["second_brain"]["exported"] == 0
    assert sink.retracts == [event_id, event_id]
    assert sink.calls == export_calls
    assert service.repository.get_event(event_id).sink_state == "pending"


def test_episode_grouping_is_deterministic(settings: object) -> None:
    repository = Repository(settings)
    base = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    first = batch_from(
        event_dict(
            event_id="phevt:episode:001",
            occurred_at=base.isoformat(),
            project_hint="project-a",
        )
    ).events[0]
    second = batch_from(
        event_dict(
            event_id="phevt:episode:002",
            occurred_at=(base + timedelta(minutes=10)).isoformat(),
            project_hint="project-a",
        )
    ).events[0]
    third = batch_from(
        event_dict(
            event_id="phevt:episode:003",
            occurred_at=(base + timedelta(minutes=50)).isoformat(),
            project_hint="project-a",
        )
    ).events[0]
    for event in (first, second, third):
        repository.ingest_event("iphone", event, candidate_payload=None)
    assert repository.rebuild_episodes() == 2
    snapshot = repository.episodes()
    assert [episode["event_count"] for episode in snapshot] == [1, 2]
    assert repository.rebuild_episodes() == 2
    assert repository.episodes() == snapshot


def test_original_attachments_have_no_default_expiry(
    settings: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHONE_HISTORY_API_TOKEN", settings.api_token)
    monkeypatch.setenv(
        "PHONE_HISTORY_MASTER_KEY_B64", base64.urlsafe_b64encode(settings.master_key).decode()
    )
    monkeypatch.delenv("PHONE_HISTORY_ATTACHMENT_RETENTION_DAYS", raising=False)
    assert Settings.from_environment().attachment_retention_days is None
    assert settings.attachment_retention_days is None
    repository = Repository(settings)
    event = batch_from(event_dict(event_id="phevt:retention:001", attachment=b"permanent")).events[
        0
    ]
    repository.ingest_event("iphone", event, candidate_payload=None)
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT expires_at FROM attachments").fetchone()[0] is None
    assert repository.get_event(event.id).attachment["retained_until"] is None
    assert repository.prune_expired_attachments(now=datetime.max.replace(tzinfo=UTC)) == 0
    assert repository.status()["attachments"] == 1


def test_migration_clears_legacy_expiry_without_deleting_original_or_derived_rows(
    settings: object,
) -> None:
    repository = Repository(replace(settings, attachment_retention_days=1))
    event = batch_from(event_dict(event_id="phevt:legacy:001", attachment=b"keep original")).events[
        0
    ]
    repository.ingest_event("iphone", event, candidate_payload=_candidate("Derived", "Keep"))
    with sqlite3.connect(settings.database_path) as connection:
        relative = connection.execute("SELECT storage_path FROM attachments").fetchone()[0]
        connection.execute("ALTER TABLE attachments RENAME TO attachments_old")
        connection.execute(
            "CREATE TABLE attachments ("
            "id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE "
            "REFERENCES events(id) ON DELETE CASCADE,"
            "content_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),"
            "metadata_enc BLOB NOT NULL, storage_path TEXT NOT NULL UNIQUE,"
            "expires_at TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        deadline = "2000-01-01T00:00:00.000Z"
        connection.execute(
            "INSERT INTO attachments SELECT id,event_id,content_sha256,size_bytes,metadata_enc,"
            "storage_path,?,created_at FROM attachments_old",
            (deadline,),
        )
        connection.execute("DROP TABLE attachments_old")
        connection.execute("CREATE TABLE derived_cache (payload TEXT, expires_at TEXT)")
        connection.execute("INSERT INTO derived_cache VALUES (?, ?)", ("push payload", deadline))
    original = settings.attachment_dir / relative
    encrypted = original.read_bytes()

    migrated = Repository(settings)
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT expires_at FROM attachments").fetchone()[0] is None
        assert connection.execute("SELECT payload,expires_at FROM derived_cache").fetchone() == (
            "push payload",
            deadline,
        )
        assert connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    assert original.read_bytes() == encrypted
    assert migrated.get_event(event.id).attachment["retained_until"] is None
    assert migrated.prune_expired_attachments(now=datetime.now(UTC)) == 0
    assert original.read_bytes() == encrypted
    assert migrated.status()["attachments"] == 1


def test_idempotency_response_is_encrypted_at_rest(settings: object) -> None:
    repository = Repository(settings, SecretBox(settings.master_key))
    response = {"marker": "IDEMPOTENCY_PRIVATE_MARKER_198f2e", "accepted": 1}
    repository.put_idempotency(
        "request-private-0001",
        "0" * 64,
        status=201,
        response=response,
    )
    assert repository.get_idempotency("request-private-0001", "0" * 64).response == response
    database_bytes = settings.database_path.read_bytes()
    assert b"IDEMPOTENCY_PRIVATE_MARKER_198f2e" not in database_bytes
