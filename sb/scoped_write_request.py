"""Additive scoped request codec. No provider acceptance or authority is granted."""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import assert_never

from sb.effect_values import JsonValue
from sb.scoped_write_preparation import ScopedWritePreparation, decode_scoped_write_preparation
from sb.write_request_values import WriteRequestRejected, canonical_bytes, parse_request_v3

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_KEYS = frozenset(["schema_version", "profile", "provider_instance_id", "operation", "source_request", "preparation", "writer", "created_at", "expires_at", "idempotency_key", "request_digest", "request_id"])


def _hash(domain: str, value: JsonValue) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(domain.encode() + b"\0" + raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopedWriteRequest:
    canonical: bytes
    preparation: ScopedWritePreparation
    request_id: str
    request_digest: str
    idempotency_key: str
    provider_instance_id: str
    expires_at: datetime


def parse_scoped_write_request(value: JsonValue, *, now: datetime, expected_provider: str) -> ScopedWriteRequest:
    """Validate request bytes, original V3 receipt and scope/body bindings.

    The authenticated transport, current policy, consumed scope review and durable
    acceptance ledger must be checked separately before materializing anything.
    """
    try:
        if not isinstance(value, dict) or frozenset(value) != _KEYS or type(value["schema_version"]) is not int or value["schema_version"] != 4:
            raise ValueError
        if value["profile"] != "scoped-remember-v1" or value["operation"] != "remember":
            raise ValueError
        provider = value["provider_instance_id"]
        if not isinstance(provider, str) or not _ID.fullmatch(provider) or provider != expected_provider:
            raise ValueError
        raw = canonical_bytes(value)
        if len(raw) > 32768:
            raise ValueError
        source = parse_request_v3(value["source_request"], now)
        prepared = decode_scoped_write_preparation(value["preparation"], now=now)
        identity = prepared.identity
        if (identity.candidate_id != source.candidate_id
            or identity.candidate_digest != source.candidate_digest
            or identity.classification_digest != source.classification_digest):
            raise ValueError
        if (source.subject != prepared.subject or source.payload["content"] != prepared.content
            or source.sensitivity != prepared.sensitivity or source.retention_days != prepared.retention_days):
            raise ValueError
        writer = value["writer"]
        if not isinstance(writer, dict) or set(writer) != {"principal_id", "agent_id", "session_id"} or writer["principal_id"] != prepared.source_access.owner:
            raise ValueError
        for name in ("agent_id", "session_id"):
            field = writer[name]
            match field:
                case str():
                    if _ID.fullmatch(field) is None:
                        raise ValueError
                case int() | float() | list() | dict() | None:
                    raise ValueError
                case _:
                    assert_never(field)
        expires_at = value["expires_at"]
        if not isinstance(expires_at, str):
            raise TypeError
        expires = datetime.fromisoformat(expires_at)
        if expires.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value["expires_at"] or value["created_at"] != source.created_at:
            raise ValueError
        if not now < expires <= min(prepared.expires_at, datetime.fromisoformat(source.expires_at)):
            raise ValueError
        key = "memidem:scoped:v4:" + _hash("orca-jarvis/memory-scoped-write-idempotency/v4", {
            "provider_instance_id": provider, "identity_digest": prepared.identity.identity_digest})[7:]
        digest = _hash("orca-jarvis/memory-scoped-write-request/v4", {k: v for k, v in value.items() if k not in {"request_id", "request_digest"}})
        if value["idempotency_key"] != key or value["request_digest"] != digest or value["request_id"] != "memreq:scoped:v4:" + digest[7:]:
            raise ValueError
        return ScopedWriteRequest(raw, prepared, "memreq:scoped:v4:" + digest[7:], digest, key, provider, expires)
    except (ValueError, TypeError, KeyError, UnicodeError, WriteRequestRejected) as exc:
        raise ValueError("SCOPED_WRITE_REQUEST_INVALID") from exc
