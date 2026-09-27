
import pytest

from sb.effect_values import JsonObject
from sb.scoped_write_identity import scoped_write_identity


def material() -> JsonObject:
    return {"schema_version": 1, "operation": "remember", "candidate_id": "memcand:pos:v1:" + "a" * 64,
            "candidate_digest": "sha256:" + "b" * 64, "classification_digest": "sha256:" + "c" * 64,
            "source_digest": "sha256:" + "d" * 64, "owner": "principal:owner",
            "projects": ["project:a"], "policy_revision": "policy:1"}


def test_scope_changes_identity_and_key():
    first = scoped_write_identity(material())
    assert first == scoped_write_identity(dict(reversed(list(material().items()))))
    other = scoped_write_identity({**material(), "projects": ["project:b"]})
    assert first.identity_digest != other.identity_digest
    assert first.idempotency_key != other.idempotency_key


@pytest.mark.parametrize("changes", [{"schema_version": True}, {"projects": ["*"]},
    {"projects": ["project:a", "project:a"]}, {"projects": ["project:b", "project:a"]},
    {"projects": ["project:"]}, {"owner": "someone"}, {"extra": 1}, {"operation": "correct"}])
def test_rejects_invalid_identity(changes: JsonObject):
    with pytest.raises(ValueError, match="SCOPED_WRITE_IDENTITY_INVALID"):
        _ = scoped_write_identity({**material(), **changes})
