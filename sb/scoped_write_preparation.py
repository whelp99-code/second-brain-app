"""Decode JARVIS scoped preparation, without accepting or authorizing a write."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sb.effect_values import JsonObject, JsonValue
from sb.remember_body import plain_text_body
from sb.scoped_write_identity import ScopedWriteIdentity, scoped_write_identity
from sb.source_access import SourceAccess

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _object(value: JsonValue, keys: str) -> JsonObject:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("SCOPED_WRITE_PREPARATION_INVALID")
    return value


def _hash(domain: str, value: JsonValue) -> str:
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(domain.encode() + b"\0" + raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopedWritePreparation:
    identity: ScopedWriteIdentity
    source_access: SourceAccess
    subject: str
    content: str
    sensitivity: str
    retention_days: int
    expires_at: datetime
    preparation_digest: str
    canonical: bytes
    content_digest: str


def decode_scoped_write_preparation(value: JsonValue, *, now: datetime) -> ScopedWritePreparation:
    """Check bytes and scope binding. Callers still need current write authority,
    policy validation, atomic review consumption and the versioned request contract.
    No file, ledger, provider request or approval is created here.
    """
    try:
        root = _object(
            value, "schema_version profile binding payload writes_authorized preparation_digest"
        )
        if (
            type(root["schema_version"]) is not int
            or root["schema_version"] != 1
            or root["profile"] != "scoped-remember-preparation-v1"
            or root["writes_authorized"] is not False
        ):
            raise ValueError
        binding = _object(
            root["binding"],
            "identity identity_digest proposal_digest idempotency_key control_request_id control_receipt_id command_digest expires_at writes_authorized",
        )
        identity = scoped_write_identity(binding["identity"])
        if (
            binding["writes_authorized"] is not False
            or binding["identity_digest"] != identity.identity_digest
            or binding["idempotency_key"] != identity.idempotency_key
        ):
            raise ValueError
        for key in ("proposal_digest", "command_digest"):
            digest = binding[key]
            if not isinstance(digest, str):
                raise TypeError
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError
        for key in ("control_request_id", "control_receipt_id"):
            item = binding[key]
            if (
                not isinstance(item, str)
                or not item
                or len(item.encode()) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in item)
            ):
                raise ValueError
        expires_at = binding["expires_at"]
        if not isinstance(expires_at, str):
            raise TypeError
        expires = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        if (
            expires.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            != expires_at
            or now.tzinfo is None
            or now.utcoffset() is None
            or now >= expires
        ):
            raise ValueError
        payload = _object(
            root["payload"],
            "subject content subject_digest content_digest purpose sensitivity retention_days",
        )
        subject = payload["subject"]
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject.encode()) > 512
            or unicodedata.normalize("NFC", subject) != subject
            or any(ord(c) < 32 or ord(c) == 127 for c in subject)
        ):
            raise ValueError
        content = plain_text_body(payload["content"])
        content_digest = _hash("orca-jarvis/memory-content/v1", content)
        if payload["subject_digest"] != _hash("orca-jarvis/memory-subject/v1", subject) or payload[
            "content_digest"
        ] != content_digest:
            raise ValueError
        if (
            payload["purpose"] != "personal_memory"
            or payload["sensitivity"] not in ("public", "personal", "sensitive", "restricted")
            or type(payload["retention_days"]) is not int
            or not 1 <= payload["retention_days"] <= 3650
        ):
            raise ValueError
        expected = _hash(
            "orca-jarvis/memory-scoped-write-preparation/v1",
            {k: v for k, v in root.items() if k != "preparation_digest"},
        )
        if root["preparation_digest"] != expected:
            raise ValueError
        return ScopedWritePreparation(
            identity,
            SourceAccess("principal:owner", identity.projects, identity.policy_revision),
            subject,
            content,
            payload["sensitivity"],
            payload["retention_days"],
            expires,
            expected,
            json.dumps(
                root, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode(),
            content_digest,
        )
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise ValueError("SCOPED_WRITE_PREPARATION_INVALID") from exc
