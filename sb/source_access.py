"""Trusted source configuration labels; these labels alone grant no access."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _identifier(value: object, prefix: str = "") -> bool:
    return (isinstance(value, str) and value.startswith(prefix) and _ID.fullmatch(value) is not None
        and _ID.fullmatch(value.removeprefix(prefix)) is not None)


def _projects(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    values = cast(tuple[object, ...], value)
    return (len(values) <= 64 and all(_identifier(item, "project:") for item in values)
        and values == tuple(sorted(set(cast(tuple[str, ...], values)))))


@dataclass(frozen=True, slots=True)
class SourceAccess:
    owner: str
    projects: tuple[str, ...]
    policy_revision: str

    def __post_init__(self) -> None:
        if not (_identifier(self.owner, "principal:") and _identifier(self.policy_revision) and _projects(self.projects)):
            raise ValueError("SOURCE_ACCESS_INVALID")

    def encode(self) -> str:
        return json.dumps({"schema_version": 1, "owner": self.owner, "projects": self.projects,
            "policy_revision": self.policy_revision}, sort_keys=True, separators=(",", ":"))


def source_access_identity(source_id: str, source_uri: str, content_hash: str) -> str:
    if not source_id or not source_uri or _HASH.fullmatch(content_hash) is None:
        raise ValueError("SOURCE_ACCESS_IDENTITY_INVALID")
    value = json.dumps([source_id, source_uri, content_hash], ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(b"second-brain/source-access-identity/v1\0" + value.encode()).hexdigest()


def source_access_digest(identity: str, access: SourceAccess) -> str:
    return "sha256:" + hashlib.sha256(b"second-brain/source-access-classification/v1\0"
        + identity.encode() + b"\0" + access.encode().encode()).hexdigest()
