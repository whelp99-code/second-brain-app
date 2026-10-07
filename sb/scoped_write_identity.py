"""Scope-bound write identity codec; not a provider authorization surface."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import assert_never

from sb.effect_values import JsonValue

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CANDIDATE = re.compile(r"memcand:pos:v1:[0-9a-f]{64}\Z")
_KEYS = frozenset({"schema_version", "operation", "candidate_id", "candidate_digest",
                   "classification_digest", "source_digest", "owner",
                   "projects", "policy_revision"})
_DOMAIN = b"orca-jarvis/memory-scoped-write-identity/v1\0"


@dataclass(frozen=True, slots=True)
class ScopedWriteIdentity:
    canonical: bytes
    identity_digest: str
    idempotency_key: str
    candidate_id: str
    candidate_digest: str
    classification_digest: str
    projects: tuple[str, ...]
    policy_revision: str


def scoped_write_identity(value: JsonValue) -> ScopedWriteIdentity:
    """Validate public identity material; a matching digest never grants a write."""
    if not isinstance(value, dict) or frozenset(value) != _KEYS:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if value["operation"] != "remember" or value["owner"] != "principal:owner":
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    fields: dict[str, str] = {}
    for key, pattern in (("candidate_id", _CANDIDATE), ("policy_revision", _ID),
                         *((key, _DIGEST) for key in ("candidate_digest", "classification_digest",
                                                     "source_digest"))):
        field = value[key]
        match field:
            case str() if pattern.fullmatch(field) is not None:
                fields[key] = field
            case str() | int() | float() | list() | dict() | None:
                raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
            case _:
                assert_never(field)
    projects = value["projects"]
    if not isinstance(projects, list) or len(projects) > 64:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    project_ids: list[str] = []
    for item in projects:
        match item:
            case str() if item.startswith("project:") and _ID.fullmatch(item) and _ID.fullmatch(item[8:]):
                project_ids.append(item)
            case str() | int() | float() | list() | dict() | None:
                raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
            case _:
                assert_never(item)
    if project_ids != sorted(set(project_ids)):
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(_DOMAIN + canonical).hexdigest()
    return ScopedWriteIdentity(
        canonical, f"sha256:{digest}", f"memidem:scoped:v1:{digest}",
        fields["candidate_id"], fields["candidate_digest"], fields["classification_digest"],
        tuple(project_ids), fields["policy_revision"],
    )
