"""Metadata-only source discovery contracts and scanner."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path, PurePath, PurePosixPath
from typing import Final, Literal, override

from sb.connectors.fs_safety import SafeSourceFilesystem, SafeSourceFilesystemError
from sb.connectors.source_manifest import discovery_path_allowed

SOURCE_DISCOVERY_REQUEST_V1: Final = "second-brain-source-discovery-request-v1"
SOURCE_DISCOVERY_ENTRY_V1: Final = "second-brain-source-discovery-entry-v1"
SOURCE_DISCOVERY_MANIFEST_V1: Final = "second-brain-source-discovery-manifest-v1"
SourceName = Literal["me-wiki", "unified-db", "legacy Mem0/RAG", "hermes", "dev-wiki"]
_REQUEST_FIELDS: Final = frozenset({"request_version", "source_name", "source_root"})
_ALLOWED_SUFFIXES: Final = frozenset(
    {
        ".csv",
        ".db",
        ".json",
        ".jsonl",
        ".md",
        ".parquet",
        ".sqlite",
        ".sqlite3",
        ".toml",
        ".yaml",
        ".yml",
    }
)
_SOURCE_NAMES: Final[dict[str, SourceName]] = {
    "me-wiki": "me-wiki",
    "hermes": "hermes",
    "dev-wiki": "dev-wiki",
    "unified-db": "unified-db",
    "legacy Mem0/RAG": "legacy Mem0/RAG",
}


@dataclass(frozen=True, slots=True)
class InvalidContractValue(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class SourceDiscoveryError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _string(value: str, field: str) -> str:
    if not value:
        raise InvalidContractValue(f"{field} must be a non-empty string")
    return value


def _canonical(value: Mapping[str, str | list[dict[str, str]]]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def path_digest(source_name: SourceName, entry: SourceDiscoveryEntryV1) -> str:
    """Bind a source identity to path and lstat metadata, never file bytes."""
    body = {
        "source_name": source_name,
        "relative_path": entry.relative_path,
        "kind": entry.kind,
        "size_bytes": entry.size_bytes,
        "mtime_ns": entry.mtime_ns,
        "mode": entry.mode,
    }
    return sha256(f"{SOURCE_DISCOVERY_ENTRY_V1}\0".encode() + _canonical(body)).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceDiscoveryRequestV1:
    request_version: str
    source_name: SourceName
    source_root: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, str]) -> SourceDiscoveryRequestV1:
        unknown = set(data) - _REQUEST_FIELDS
        if unknown:
            raise InvalidContractValue(f"unknown fields: {sorted(unknown)}")
        missing = _REQUEST_FIELDS - set(data)
        if missing:
            raise InvalidContractValue(f"missing required fields: {sorted(missing)}")
        version = _string(data["request_version"], "request_version")
        if version != SOURCE_DISCOVERY_REQUEST_V1:
            raise InvalidContractValue(f"unsupported request_version: {version!r}")
        root = _string(data["source_root"], "source_root")
        if not PurePath(root).is_absolute():
            raise InvalidContractValue("source_root must be a non-empty absolute path string")
        name = data["source_name"]
        if name not in _SOURCE_NAMES:
            raise InvalidContractValue("source_name is not an approved discovery source")
        return cls(version, _SOURCE_NAMES[name], root)


@dataclass(frozen=True, slots=True)
class SourceDiscoveryEntryV1:
    relative_path: str
    kind: str
    size_bytes: str
    mtime_ns: str
    mode: str
    path_digest: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "mode": self.mode,
            "path_digest": self.path_digest,
        }


@dataclass(frozen=True, slots=True)
class SourceDiscoveryManifestV1:
    manifest_version: str
    request_version: str
    source_name: SourceName
    source_root: str
    entry_count: str
    body_reads: str
    entries: tuple[SourceDiscoveryEntryV1, ...]
    manifest_digest: str

    @classmethod
    def create(
        cls,
        request: SourceDiscoveryRequestV1,
        entries: tuple[SourceDiscoveryEntryV1, ...],
    ) -> SourceDiscoveryManifestV1:
        provisional = cls(
            SOURCE_DISCOVERY_MANIFEST_V1,
            request.request_version,
            request.source_name,
            request.source_root,
            str(len(entries)),
            "0",
            entries,
            "0" * 64,
        )
        return replace(provisional, manifest_digest=provisional.computed_digest())

    def computed_digest(self) -> str:
        body: dict[str, str | list[dict[str, str]]] = {
            "manifest_version": self.manifest_version,
            "request_version": self.request_version,
            "source_name": self.source_name,
            "source_root": self.source_root,
            "entry_count": self.entry_count,
            "body_reads": self.body_reads,
            "entries": [entry.to_mapping() for entry in self.entries],
        }
        return sha256(f"{SOURCE_DISCOVERY_MANIFEST_V1}\0".encode() + _canonical(body)).hexdigest()


def is_allowed_source_suffix(relative_path: str) -> bool:
    """Return True when the file suffix is an approved discovery/import type."""
    suffix = Path(relative_path).suffix.casefold()
    return bool(suffix) and suffix in _ALLOWED_SUFFIXES


def discover_source(
    request: SourceDiscoveryRequestV1,
    filesystem: SafeSourceFilesystem | None = None,
) -> SourceDiscoveryManifestV1:
    """Discover approved regular files without reading any source body."""
    root = Path(request.source_root)
    client = filesystem or SafeSourceFilesystem((root,))
    try:
        scanned = client.scan(root, reject_denied=True)
    except SafeSourceFilesystemError as exc:
        raise SourceDiscoveryError(str(exc)) from exc
    entries: list[SourceDiscoveryEntryV1] = []
    for item in scanned.files:
        if not discovery_path_allowed(request.source_name, item.relative_path):
            continue
        if not is_allowed_source_suffix(item.relative_path):
            raise SourceDiscoveryError(f"unsupported source file suffix: {item.relative_path}")
        relative = item.relative_path
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or relative != pure.as_posix()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise SourceDiscoveryError("relative_path must be a canonical relative POSIX path")
        entry = SourceDiscoveryEntryV1(
            relative,
            "file",
            str(item.metadata.st_size),
            str(item.metadata.st_mtime_ns),
            str(item.metadata.st_mode),
            "0" * 64,
        )
        entries.append(replace(entry, path_digest=path_digest(request.source_name, entry)))
    return SourceDiscoveryManifestV1.create(request, tuple(entries))
