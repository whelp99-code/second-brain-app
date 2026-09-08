"""Scope-bound write identity codec; not a provider authorization surface."""

import hashlib
import json
import re
from dataclasses import dataclass

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


def scoped_write_identity(value: object) -> ScopedWriteIdentity:
    """Validate public identity material; a matching digest never grants a write."""
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if value["operation"] != "remember" or value["owner"] != "principal:owner":
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    for key, pattern in (("candidate_id", _CANDIDATE), ("policy_revision", _ID),
                         *((key, _DIGEST) for key in ("candidate_digest", "classification_digest",
                                                     "source_digest"))):
        if not isinstance(value[key], str) or not pattern.fullmatch(value[key]):
            raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    projects = value["projects"]
    if not isinstance(projects, list) or len(projects) > 64:
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if any(not isinstance(item, str) or not item.startswith("project:")
           or not _ID.fullmatch(item) or not _ID.fullmatch(item[8:]) for item in projects):
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    if projects != sorted(set(projects)):
        raise ValueError("SCOPED_WRITE_IDENTITY_INVALID")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(_DOMAIN + canonical).hexdigest()
    return ScopedWriteIdentity(canonical, f"sha256:{digest}", f"memidem:scoped:v1:{digest}")
