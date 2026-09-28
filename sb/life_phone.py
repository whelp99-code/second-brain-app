"""Translate an explicit Phone History event into a source-bound life input.

Client knowledge/approval/scope labels never grant authority. The core's source
configuration owns policy; an HTTP ingress is not a direct Vault write.
"""

from __future__ import annotations

import base64
import re
from hashlib import sha256

from sb.life_attachments import inline
from sb.life_contracts import SENSITIVITIES, LifeInputError
from sb.life_values import canonical_bytes, instant, text

TYPES = {
    "note": "note_saved",
    "text_saved": "note_saved",
    "quick_memo": "note_saved",
    "quick_note": "note_saved",
    "text_shared": "note_saved",
    "file_shared": "document_saved",
    "webpage_saved": "link_saved",
    "photo_saved": "photo_saved",
    "audio_saved": "audio_saved",
    "call_recording": "call_recording_imported",
    "call_recording_imported": "call_recording_imported",
    "activity_started": "activity_started",
    "task_started": "task_started",
    "task_completed": "task_completed",
}


def phone_event(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
    allowed = {
        "schema_version",
        "id",
        "device_id",
        "occurred_at",
        "source",
        "event_type",
        "capture_mode",
        "sensitivity",
        "title",
        "body",
        "url",
        "project_hint",
        "attachment",
        "attachments",
        "metadata",
        "knowledge_status",
        "approval_status",
        "canonical",
    }
    if set(document) - allowed:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    version = document.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
    if document.get("sensitivity", "personal") not in SENSITIVITIES:
        raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
    identity = text(document.get("id"), maximum=128)
    if re.fullmatch(r"[A-Za-z0-9._:-]+", identity) is None:
        raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
    device = text(document.get("device_id"), maximum=256)
    event_type = TYPES.get(document.get("event_type"))
    if event_type is None or document.get("capture_mode") not in {"explicit", "share", "shortcut"}:
        raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
    occurred = instant(document.get("occurred_at"))
    body = text(document.get("body") or "", maximum=100000, empty=True)
    url = document.get("url")
    if url is not None:
        from urllib.parse import urlsplit

        url = text(url, maximum=4096)
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise LifeInputError("LIFE_PHONE_URL_INVALID")
        body += "\n" + url
    attachments = []
    raw_attachments = document.get("attachment", document.get("attachments"))
    if raw_attachments is not None:
        values = raw_attachments if isinstance(raw_attachments, list) else [raw_attachments]
        if len(values) > 3:
            raise LifeInputError("LIFE_ATTACHMENT_INVALID")
        for attachment in values:
            if not isinstance(attachment, dict):
                raise LifeInputError("LIFE_ATTACHMENT_INVALID")
            encoded = attachment.get("content_base64") or attachment.get("data_base64")
            name = attachment.get("filename") or attachment.get("name")
            mime = (
                attachment.get("media_type")
                or attachment.get("mime_type")
                or attachment.get("mimeType")
                or attachment.get("content_type")
            )
            if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
                raise LifeInputError("LIFE_ATTACHMENT_INVALID")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise LifeInputError("LIFE_ATTACHMENT_INVALID") from exc
            item = inline(name, mime, data)
            declared = attachment.get("sha256") or attachment.get("content_sha256")
            if declared is not None and declared != item["sha256"]:
                raise LifeInputError("LIFE_ATTACHMENT_DIGEST_MISMATCH")
            attachments.append(item)
    if document.get("event_type") == "file_shared":
        if not attachments:
            raise LifeInputError("LIFE_PHONE_FILE_REQUIRED")
        if all(a["mime"].startswith("audio/") for a in attachments):
            event_type = "audio_saved"
        elif all(a["mime"].startswith("image/") for a in attachments):
            event_type = "photo_saved"
    metadata = document.get("metadata") or {}
    if event_type == "call_recording_imported":
        if not attachments or not all(a["mime"].startswith("audio/") for a in attachments):
            raise LifeInputError("LIFE_PHONE_CALL_AUDIO_REQUIRED")
        if not isinstance(metadata, dict):
            raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
        # capture_mode is the legacy declaration. An explicit false overrides it.
        if "recording_declared" in metadata and metadata.get("recording_declared") is not True:
            raise LifeInputError("LIFE_PHONE_RECORDING_UNDECLARED")
        if document.get("capture_mode") not in {"explicit", "share", "shortcut"}:
            raise LifeInputError("LIFE_PHONE_RECORDING_UNDECLARED")
        duration = metadata.get("duration_seconds")
        method = metadata.get("capture_method", document.get("capture_mode"))
        if duration is not None and (type(duration) is not int or not 0 <= duration <= 86400):
            raise LifeInputError("LIFE_PHONE_RECORDING_INVALID")
        if method not in {"explicit", "share", "shortcut"}:
            raise LifeInputError("LIFE_PHONE_RECORDING_INVALID")
        primary = attachments[0]
        body += "\n" + "\n".join(
            (
                "통화 분류는 사용자가 명시한 기록입니다. 전사는 별도 상태입니다.",
                "attachment_state=untranscribed",
                "recording_sha256=" + primary["sha256"],
                "recording_locator=attachment:" + primary["name"],
                "capture_method=" + str(method),
                "occurred_at=" + occurred.isoformat(),
                "duration_seconds=" + (str(duration) if duration is not None else "unknown"),
                "audio_format=" + primary["mime"],
                "transcript_revision=separate",
            )
        )
    # Keep the original signed/unsigned client event as DATA, never as an
    # authority for a scope, project or verified decision.
    raw = canonical_bytes(document)
    return {
        "source_item_id": "phone:" + sha256(device.encode()).hexdigest()[:16] + ":" + identity,
        "source_version": sha256(raw).hexdigest(),
        "event_type": event_type,
        "title": text(document.get("title") or document.get("event_type"), maximum=1000),
        "body": body,
        "occurred_start": occurred.isoformat(),
        "timezone": "UTC",
        "time_precision": "exact",
        "event_status": "occurred",
        "evidence_level": "user_asserted",
        "review_state": "unreviewed",
        "attachments": attachments or [inline("phone-event.json", "application/json", raw)],
    }
