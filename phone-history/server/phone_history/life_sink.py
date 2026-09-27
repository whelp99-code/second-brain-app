"""Optional HTTP life inbox sink. It only accepts/retracts evidence, never runs AI.

The existing encrypted Phone History repository retains attachments. This sink
sends redacted metadata and requires an explicit matching durable receipt. It
never marks intake as search, Obsidian, canonical or device acceptance success.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from phone_history.redaction import redact_fields
from phone_history.repository import EventRecord
from phone_history.sink import SinkError

_MAX_RESPONSE = 1024 * 1024
_EVENT_TYPES = {
    "quick_note": "note_saved",
    "text_shared": "note_saved",
    "task_started": "activity",
    "note": "note_saved",
    "text_saved": "note_saved",
    "note_saved": "note_saved",
    "webpage_saved": "webpage_saved",
    "link_shared": "webpage_saved",
    "photo_saved": "photo_saved",
    "image_shared": "photo_saved",
    "audio_saved": "audio_saved",
    "call_recording": "call_recording_imported",
    "call_recording_imported": "call_recording_imported",
    "activity_started": "activity",
    "file_shared": "document_saved",
    "document_saved": "document_saved",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        raise SinkError("life_redirect_refused")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise SinkError("life_identifier_invalid")
    if not all(c.isascii() and (c.isalnum() or c in "._:-") for c in value):
        raise SinkError("life_identifier_invalid")
    return value


@dataclass(frozen=True, slots=True)
class LifeInboxSink:
    base_url: str
    source_id: str
    token_env: str
    timeout: int = 10

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SinkError("life_endpoint_invalid")
        _identifier(self.source_id)
        if not self.token_env.startswith("SB_LIFE_") or not all(
            c.isupper() or c.isdigit() or c == "_" for c in self.token_env
        ):
            raise SinkError("life_device_token_required")
        if not 1 <= self.timeout <= 30:
            raise SinkError("life_timeout_invalid")

    def _request(self, path: str, body: object | None = None) -> dict:
        token = os.environ.get(self.token_env, "")
        if len(token) < 24:
            raise SinkError("life_device_token_missing")
        raw = None if body is None else _canonical(body).encode()
        if raw is not None and len(raw) > 256 * 1024:
            raise SinkError("life_payload_too_large")
        request = Request(
            self.base_url.rstrip("/") + "/api/life/v1" + path,
            data=raw,
            method="GET" if raw is None else "POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                payload = response.read(_MAX_RESPONSE + 1)
                if len(payload) > _MAX_RESPONSE:
                    raise SinkError("life_response_too_large")
                result = json.loads(payload)
        except HTTPError as exc:
            raise SinkError(f"life_http_{exc.code}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise SinkError("life_transport_unavailable") from exc
        if not isinstance(result, dict):
            raise SinkError("life_response_invalid")
        return result

    def export(self, event: EventRecord) -> str:
        fields, _, _ = redact_fields(event.title, event.body, event.url, event.project_hint)
        title, body, url, project_hint = fields
        event_type = _EVENT_TYPES.get(event.event_type)
        if event_type is None:
            raise SinkError("life_event_type_unsupported")
        full_title = title or event.event_type.replace("_", " ")
        bounded_title = full_title.encode()[:500].decode("utf-8", errors="ignore")
        original = {
            "phone_event_id": event.id,
            "device_id_digest": _digest(event.device_id),
            "phone_event_digest": event.event_digest,
            "title": full_title,
            "body": body,
            "url": url,
            "project_hint": project_hint,
            "attachment": event.attachment,
            "attachment_state": "not_transcribed"
            if event_type in {"audio_saved", "call_recording_imported"}
            else "metadata_only",
            "attachment_original_store": "phone_history_encrypted_repository",
            "capture_mode": event.capture_mode,
        }
        source_item = "phone:" + _digest(event.device_id + "\0" + event.id)
        life_event = {
            "source_id": self.source_id,
            "source_item_id": source_item,
            "source_version": event.event_digest,
            "title": bounded_title,
            "body": _canonical(original),
            "event_type": event_type,
            "event_status": "occurred",
            "evidence_level": "user_asserted",
            "review_state": "unreviewed",
            "occurred_start": event.occurred_at,
            "observed_at": event.occurred_at,
            "timezone": "Asia/Seoul",
            "time_precision": "exact",
            "sensitivity": event.sensitivity,
            "external_processing": "local_only",
        }
        # A captured audio/file occurrence is not evidence of its interpreted contents.
        if len(life_event["body"].encode()) > 65536:
            raise SinkError("life_payload_too_large")
        key = "phone-intake:" + _digest(source_item + "\0" + event.event_digest)
        accepted = self._request("/events:batch", {"idempotency_key": key, "events": [life_event]})
        receipt_id = _identifier(accepted.get("receipt_id"))
        receipt = self._request("/receipts/" + receipt_id)
        if receipt.get("durable") is not True or receipt.get("receipt_id") != receipt_id:
            raise SinkError("life_durable_receipt_missing")
        items = receipt.get("events")
        if not isinstance(items, list) or len(items) != 1:
            raise SinkError("life_event_receipt_missing")
        item = items[0]
        if (
            not isinstance(item, dict)
            or item.get("source_id") != self.source_id
            or item.get("source_item_id") != source_item
            or item.get("state") not in {"accepted", "processed"}
        ):
            raise SinkError("life_event_receipt_mismatch")
        event_id = _identifier(item.get("event_id"))
        reference = {
            "source_id": self.source_id,
            "source_item_id": source_item,
            "event_id": event_id,
        }
        upload_id = "life:" + base64.urlsafe_b64encode(
            _canonical(reference).encode()
        ).decode().rstrip("=")
        return _canonical(
            {
                "upload_id": upload_id,
                "receipt_id": receipt_id,
                "event_id": event_id,
                "content_sha256": _digest(_canonical(life_event)),
                "intake_only": True,
                "searchable": item.get("searchable") is True,
                "projected": False,
                "canonical": False,
                "transcription": "NOT_RUN",
            }
        )

    def retract(self, upload_id: str) -> str:
        if not upload_id.startswith("life:") or len(upload_id) > 4096:
            raise SinkError("life_retract_reference_invalid")
        try:
            encoded = upload_id[5:]
            reference = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (ValueError, UnicodeError) as exc:
            raise SinkError("life_retract_reference_invalid") from exc
        if (
            not isinstance(reference, dict)
            or set(reference) != {"source_id", "source_item_id", "event_id"}
            or reference["source_id"] != self.source_id
        ):
            raise SinkError("life_retract_reference_invalid")
        event_id = _identifier(reference["event_id"])
        source_item = reference["source_item_id"]
        if (
            not isinstance(source_item, str)
            or not source_item.startswith("phone:")
            or len(source_item) != 70
        ):
            raise SinkError("life_retract_reference_invalid")
        result = self._request(
            "/source-retractions",
            {
                "source_id": self.source_id,
                "source_item_id": source_item,
                "event_id": event_id,
                "idempotency_key": "phone-retract:" + _digest(upload_id),
                "reason": "Phone History source explicitly retracted by its owner",
            },
        )
        receipt_id = _identifier(result.get("receipt_id"))
        receipt = self._request("/receipts/" + receipt_id)
        items = receipt.get("events")
        if (
            receipt.get("durable") is not True
            or not isinstance(items, list)
            or len(items) != 1
            or items[0].get("event_id") != event_id
            or items[0].get("state") != "deleted"
        ):
            raise SinkError("life_retraction_pending")
        return _canonical(
            {
                "deleted": True,
                "receipt_id": receipt_id,
                "event_id": event_id,
                "raw_physical_purge": False,
                "offline_replica_removal": "PENDING_SYNC",
            }
        )

    def status(self, event_id: str) -> dict:
        # Status read is optional; callers must not conflate export with publication.
        event_id = _identifier(event_id)
        return self._request("/events/" + event_id + "?" + urlencode({"include": "status"}))
