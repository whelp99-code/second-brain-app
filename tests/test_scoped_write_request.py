
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_values import JsonObject, JsonValue
from sb.scoped_write_request import parse_scoped_write_request
from sb.write_request_values import WriteRequestRejected, parse_request_v3
from tests.json_fixtures import parse_object

NOW = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)


def value():
    return parse_object((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())


def parse(request: JsonObject):
    created_at = request["created_at"]
    assert isinstance(created_at, str)
    # Captured JARVIS fixture uses its own deterministic candidate creation time.
    return parse_scoped_write_request(request, now=datetime.fromisoformat(created_at), expected_provider="provider:fixture")


def rehash(request: JsonObject) -> None:
    base = {k: v for k, v in request.items() if k not in {"request_digest", "request_id"}}
    raw = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(b"orca-jarvis/memory-scoped-write-request/v4\0" + raw).hexdigest()
    request.update(request_digest="sha256:" + digest, request_id="memreq:scoped:v4:" + digest)


def test_actual_jarvis_request_roundtrip_and_legacy_rejection():
    request = value()
    created_at = request["created_at"]
    assert isinstance(created_at, str)
    parsed = parse(request)
    assert parsed.preparation.content == "첫 결정\r\n두 번째 결정\n반복\n반복 [^user]"
    assert parsed.preparation.source_access.projects == ("project:shared-memory",)
    assert json.loads(parsed.canonical) == request
    with pytest.raises(WriteRequestRejected):
        _ = parse_request_v3(request, datetime.fromisoformat(created_at))
    writer = request["writer"]
    assert isinstance(writer, dict)
    writer["agent_id"] = "changed"
    assert json.loads(parsed.canonical)["writer"]["agent_id"] != "changed"


@pytest.mark.parametrize("path,replacement", [
    (("provider_instance_id",), "provider:other"),
    (("schema_version",), True),
    (("writer", "principal_id"), "principal:other"),
    (("writer", "session_id"), ""),
    (("writer", "extra"), "unexpected"),
    (("source_request", "payload", "content"), "different"),
    (("preparation", "payload", "retention_days"), 3),
    (("preparation", "binding", "identity", "projects"), ["project:other"]),
    (("expires_at",), "2026-08-28T00:00:00.000Z"),
    (("idempotency_key",), "memidem:scoped:v4:" + "0" * 64),
])
def test_rehashed_wrapper_cannot_hide_invalid_nested_material(path: tuple[str, ...], replacement: JsonValue):
    request = value()
    created_at = request["created_at"]
    assert isinstance(created_at, str)
    target = request
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = replacement
    rehash(request)
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        _ = parse(request)


def test_wrong_expected_provider_and_expiry_rejected():
    request = value()
    created_at = request["created_at"]
    assert isinstance(created_at, str)
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        _ = parse_scoped_write_request(request, now=datetime.fromisoformat(created_at), expected_provider="provider:other")
    expires_at = request["expires_at"]
    assert isinstance(expires_at, str)
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        _ = parse_scoped_write_request(request, now=datetime.fromisoformat(expires_at), expected_provider="provider:fixture")


@pytest.mark.parametrize("field,replacement", [("subject", "다른 제목"), ("content", "다른 본문"), ("retention_days", 2)])
def test_individually_valid_source_request_must_match_approved_preparation(field: str, replacement: JsonValue):
    request = value()
    created_at = request["created_at"]
    assert isinstance(created_at, str)
    source = request["source_request"]
    assert isinstance(source, dict)
    if field == "content":
        payload = source["payload"]
        assert isinstance(payload, dict)
        payload["content"] = replacement
    else:
        source[field] = replacement
    base = {k: v for k, v in source.items() if k not in {"request_id", "request_digest"}}
    digest = hashlib.sha256(b"orca-jarvis/memory-write-request/v3\0" + json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source.update(request_digest="sha256:" + digest, request_id="memreq:pos:v3:" + digest)
    _ = parse_request_v3(source, datetime.fromisoformat(created_at))
    rehash(request)
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        _ = parse(request)
