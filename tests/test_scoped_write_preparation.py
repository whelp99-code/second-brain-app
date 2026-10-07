"""Captured from the compiled JARVIS v3 classify/spool/signed-review path."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_values import JsonValue
from sb.scoped_write_preparation import decode_scoped_write_preparation
from tests.json_fixtures import parse_object

NOW = datetime(2026, 8, 28, tzinfo=UTC)


def material():
    return parse_object(
        (Path(__file__).parent / "fixtures/scoped_write_preparation_v1.json").read_text()
    )


def test_actual_jarvis_preparation_preserves_scope_and_exact_bytes():
    value = material()
    decoded = decode_scoped_write_preparation(value, now=NOW)
    assert decoded.content == "첫 결정\r\n두 번째 결정\n반복\n반복 [^user]"
    assert decoded.source_access.projects == ("project:shared-memory",)
    assert decoded.preparation_digest == value["preparation_digest"]
    assert json.loads(decoded.canonical) == value
    binding = value["binding"]
    assert isinstance(binding, dict)
    identity = binding["identity"]
    assert isinstance(identity, dict)
    projects = identity["projects"]
    assert isinstance(projects, list)
    projects.append("project:other")
    assert decoded.source_access.projects == ("project:shared-memory",)
    assert json.loads(decoded.identity.canonical)["projects"] == ["project:shared-memory"]


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("writes_authorized",), True),
        (("schema_version",), True),
        (("binding", "writes_authorized"), True),
        (("binding", "identity", "projects"), ["project:other"]),
        (("binding", "identity_digest"), "sha256:" + "0" * 64),
        (("binding", "idempotency_key"), "memidem:scoped:v1:" + "0" * 64),
        (("binding", "expires_at"), "2026-01-01T00:00:00.000Z"),
        (("payload", "content"), "첫 결정\n두 번째 결정\n반복\n반복 [^user]"),
        (("payload", "subject"), "다른 제목"),
        (("payload", "retention_days"), True),
        (("payload", "extra"), "ignored?"),
        (("preparation_digest",), "sha256:" + "0" * 64),
    ],
)
def test_rejects_changed_scope_body_and_noncanonical_material(path: tuple[str, ...], replacement: JsonValue):
    value = copy.deepcopy(material())
    target = value
    for name in path[:-1]:
        nested = target[name]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match="SCOPED_WRITE_PREPARATION_INVALID"):
        _ = decode_scoped_write_preparation(value, now=NOW)


def test_expiry_and_ambiguous_clock_rejected():
    value = material()
    binding = value["binding"]
    assert isinstance(binding, dict)
    expiry_raw = binding["expires_at"]
    assert isinstance(expiry_raw, str)
    expiry = datetime.fromisoformat(expiry_raw)
    for now in (expiry, NOW.replace(tzinfo=None)):
        with pytest.raises(ValueError, match="SCOPED_WRITE_PREPARATION_INVALID"):
            _ = decode_scoped_write_preparation(value, now=now)
