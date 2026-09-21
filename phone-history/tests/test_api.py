from __future__ import annotations

import json
import socket
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from phone_history.api import build_server
from phone_history.service import PhoneHistoryService
from phone_history.transport import seal_transport_payload
from sb.store.cas import ContentAddressedStore

from tests.conftest import event_dict
from tests.test_repository_service import RecordingSink


@contextmanager
def running_api(settings: object, *, maximum: int | None = None) -> Iterator[tuple[str, object]]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    configured = replace(
        settings,
        port=port,
        max_request_bytes=maximum or settings.max_request_bytes,
    )
    service = PhoneHistoryService(configured, sink=RecordingSink())
    server = build_server(configured, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", service
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def call(
    base: str,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: object | None = None,
    headers: dict[str, str] | None = None,
    raw: bytes | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = raw
    if body is None and payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        request_headers["Content-Type"] = content_type
    request = Request(base + path, data=body, headers=request_headers, method=method)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        decoded = json.loads(exc.read())
        return exc.code, decoded, dict(exc.headers.items())
    with response:
        decoded = json.loads(response.read())
        return response.status, decoded, dict(response.headers.items())


def batch_payload(*events: dict[str, Any]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "device_id": "iphone-api-1",
        "events": list(events),
    }


def test_health_is_public_but_product_routes_require_auth(settings: object) -> None:
    with running_api(settings) as (base, _service):
        status, payload, headers = call(base, "/healthz")
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["device_closure"] == "NOT_RUN"
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"

        status, payload, _ = call(base, "/v1/capabilities")
        assert status == 401
        assert payload["error"]["code"] == "UNAUTHORIZED"

        status, payload, _ = call(
            base,
            "/v1/capabilities",
            token=settings.api_token,
        )
        assert status == 200
        assert payload["memory"]["auto_approval"] is False
        assert payload["memory"]["canonicalization"] is False


def test_http_ingest_timeline_candidate_decision_and_delete(settings: object) -> None:
    event_id = "phevt:api:001"
    with running_api(settings) as (base, _service):
        status, payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-request-0001"},
            payload=batch_payload(event_dict(event_id=event_id)),
        )
        assert status == 201
        assert payload["accepted"] == 1
        assert payload["canonicalized"] == 0
        assert payload["events"][0]["sink_state"] == "exported"
        candidate_id = payload["events"][0]["candidate_id"]

        status, replay, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-request-0001"},
            payload=batch_payload(event_dict(event_id=event_id)),
        )
        assert status == 200
        assert replay["replayed"] is True

        status, timeline, _ = call(
            base,
            "/v1/timeline?limit=10",
            token=settings.api_token,
        )
        assert status == 200
        assert [event["id"] for event in timeline["events"]] == [event_id]

        status, candidates, _ = call(
            base,
            "/v1/candidates",
            token=settings.api_token,
        )
        assert status == 200
        assert candidates["candidates"][0]["canonical"] is False

        status, decision, _ = call(
            base,
            f"/v1/candidates/{candidate_id}/decision",
            method="POST",
            token=settings.api_token,
            payload={"decision": "queue_for_owner_review"},
        )
        assert status == 200
        assert decision["state"] == "queued_for_owner_review"
        assert decision["canonical"] is False
        assert decision["approval_effect"] == "none"

        status, deleted, _ = call(
            base,
            f"/v1/events/{event_id}?reason=owner_requested",
            method="DELETE",
            token=settings.api_token,
        )
        assert status == 200
        assert deleted["state"] == "deleted"

        status, timeline, _ = call(base, "/v1/timeline", token=settings.api_token)
        assert status == 200
        assert timeline["events"] == []

        status, repeated, _ = call(
            base,
            f"/v1/events/{event_id}",
            method="DELETE",
            token=settings.api_token,
        )
        assert status == 200
        assert repeated["state"] == "already_deleted"


def test_http_idempotency_conflict_invalid_json_and_content_type(settings: object) -> None:
    with running_api(settings) as (base, _service):
        first = batch_payload(event_dict(event_id="phevt:http-conflict:001"))
        changed = batch_payload(event_dict(event_id="phevt:http-conflict:002"))
        status, _, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-conflict-0001"},
            payload=first,
        )
        assert status == 201
        status, payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-conflict-0001"},
            payload=changed,
        )
        assert status == 409
        assert payload["error"]["code"] == "CONFLICT"

        status, payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-invalid-0001"},
            raw=b"not-json",
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_ARGUMENT"

        status, payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-content-type-0001"},
            raw=b"{}",
            content_type="text/plain",
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_http_request_size_limit_and_bad_query_are_safe(settings: object) -> None:
    with running_api(settings, maximum=1024) as (base, _service):
        status, payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "api-oversize-0001"},
            raw=b"{" + b"x" * 2048 + b"}",
        )
        assert status == 413
        assert payload["error"]["code"] == "REQUEST_TOO_LARGE"

        status, payload, _ = call(
            base,
            "/v1/timeline?limit=9999",
            token=settings.api_token,
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_http_encrypted_background_ingest(settings: object) -> None:
    event_id = "phevt:encrypted-api:001"
    cleartext = batch_payload(event_dict(event_id=event_id, body="encrypted background"))
    envelope = seal_transport_payload(cleartext, settings.api_token)
    assert "encrypted background" not in json.dumps(envelope)
    with running_api(settings) as (base, _service):
        status, payload, _ = call(
            base,
            "/v1/events:encrypted",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "encrypted-api-0001"},
            payload=envelope,
        )
        assert status == 201
        assert payload["accepted"] == 1
        assert payload["events"][0]["id"] == event_id

        tampered = dict(envelope)
        encoded = tampered["payload_base64"]
        tampered["payload_base64"] = encoded[:-2] + "AA"
        status, payload, _ = call(
            base,
            "/v1/events:encrypted",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "encrypted-api-tamper"},
            payload=tampered,
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_ARGUMENT"

        status, payload, _ = call(
            base,
            "/v1/timeline?date=not-a-date",
            token=settings.api_token,
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_http_delete_retracts_isolated_vault(settings: object, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    configured = replace(settings, port=port, second_brain_vault=vault)
    service = PhoneHistoryService(configured)
    server = build_server(configured, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    event_id = "phevt:http-retract:001"
    try:
        status, _payload, _ = call(
            base,
            "/v1/events:batch",
            method="POST",
            token=settings.api_token,
            headers={"Idempotency-Key": "http-retract-0001"},
            payload=batch_payload(event_dict(event_id=event_id)),
        )
        assert status == 201
        record = service.repository.get_event(event_id)
        ref = json.loads(record.sink_ref or "{}")
        digest = ref["content_sha256"]
        staged = vault / ref["inbox_path"]
        cas = ContentAddressedStore(vault)
        cas.put(staged.read_bytes())
        db = vault / ".sb" / "search.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO search_meta(key,value) VALUES ('schema_version','4')")
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "page_id UNINDEXED, section, text, kind UNINDEXED, updated UNINDEXED, "
            "status UNINDEXED, knowledge_status UNINDEXED, approval_status UNINDEXED, "
            "canonical UNINDEXED, source_ref UNINDEXED, compact UNINDEXED, "
            "normalize_id UNINDEXED, normalize_section UNINDEXED, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO docs(page_id,section,text,kind,updated,status,knowledge_status,"
            "approval_status,canonical,source_ref,compact,normalize_id,normalize_section) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "wiki/probe",
                "body",
                f"see {digest}",
                "wiki",
                "",
                "",
                "UNVERIFIED",
                "UNREVIEWED",
                "false",
                digest,
                "",
                "",
                "",
            ),
        )
        conn.commit()
        conn.close()
        status, deleted, _ = call(
            base,
            f"/v1/events/{event_id}?reason=owner_requested",
            method="DELETE",
            token=settings.api_token,
        )
        assert status == 200
        assert deleted["state"] == "deleted"
        assert not staged.exists()
        assert cas.exists(digest) is False
        assert cas.is_tombstoned(digest) is True
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT count(*) FROM docs").fetchone()[0] == 0
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
