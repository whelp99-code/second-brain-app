"""Closed restore archive manifest and non-activating proof contracts."""

from __future__ import annotations

import hashlib
import stat
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from sb.delegations import MemoryReadFenceV1
from sb.effect_values import JsonInput, digest, format_instant
from sb.effect_write_models import ClosedModel


class RestoreArchiveEntryV1(ClosedModel):
    surface_class: str
    locator_digest: str
    file_digest: str
    mode: int
    byte_count: int
    row_count: int
    object_count: int


class RestoreArchiveManifestV1(ClosedModel):
    schema_version: Literal[1]
    archive_id: str
    archive_digest: str
    provider_instance_id: str
    source_generation_id: str
    source_generation_manifest_digest: str
    source_tombstone_sequence: int
    source_tombstone_set_root: str
    surface_manifest_digest: str
    entries: list[RestoreArchiveEntryV1] = Field(max_length=4096)
    created_at: str


class RestoreProofV1(ClosedModel):
    schema_version: Literal[1]
    request_id: str
    jarvis_fence_digest: str
    chain_snapshot_digest: str
    archive_manifest_digest: str
    surface_manifest_digest: str
    source_tombstone_sequence: int
    source_tombstone_set_root: str
    current_tombstone_sequence: int
    current_tombstone_set_root: str
    result_generation_id: str
    result_generation_digest: str
    blocked_matches: Literal[0]
    scan_errors: Literal[0]
    staging_disposal_digest: str
    proof_digest: str


class RestoreArchiveSource(ClosedModel):
    provider_instance_id: str
    source_generation_id: str
    source_generation_manifest_digest: str
    source_tombstone_sequence: int
    source_tombstone_set_root: str
    created_at: datetime


class RestoreRequest(ClosedModel):
    archive: Path
    archive_manifest: RestoreArchiveManifestV1
    jarvis_fence: MemoryReadFenceV1
    now: datetime
    request_id: str


def archive_locator(relative: Path) -> str:
    return "sha256:" + hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()


def archive_file_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def manifest_preimage(manifest: RestoreArchiveManifestV1) -> dict[str, JsonInput]:
    return {
        "schema_version": manifest.schema_version,
        "provider_instance_id": manifest.provider_instance_id,
        "source_generation_id": manifest.source_generation_id,
        "source_generation_manifest_digest": manifest.source_generation_manifest_digest,
        "source_tombstone_sequence": manifest.source_tombstone_sequence,
        "source_tombstone_set_root": manifest.source_tombstone_set_root,
        "surface_manifest_digest": manifest.surface_manifest_digest,
        "entries": [entry.model_dump(mode="json") for entry in manifest.entries],
        "created_at": manifest.created_at,
    }


def build_restore_archive_manifest(
    archive: Path,
    source: RestoreArchiveSource,
) -> RestoreArchiveManifestV1:
    """Build metadata-only authority for one isolated restore archive fixture."""
    entries: list[dict[str, JsonInput]] = []
    for path in sorted(archive.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(archive)
        payload = path.read_bytes()
        entries.append(
            {
                "surface_class": relative.parts[0],
                "locator_digest": archive_locator(relative),
                "file_digest": archive_file_digest(payload),
                "mode": stat.S_IMODE(path.stat().st_mode),
                "byte_count": len(payload),
                "row_count": 0,
                "object_count": 1,
            }
        )
    surface_digest = digest("surface", {"entries": entries})
    body: dict[str, JsonInput] = {
        "schema_version": 1,
        "provider_instance_id": source.provider_instance_id,
        "source_generation_id": source.source_generation_id,
        "source_generation_manifest_digest": source.source_generation_manifest_digest,
        "source_tombstone_sequence": source.source_tombstone_sequence,
        "source_tombstone_set_root": source.source_tombstone_set_root,
        "surface_manifest_digest": surface_digest,
        "entries": entries,
        "created_at": format_instant(source.created_at),
    }
    archive_digest = digest("generation", body)
    body["archive_id"] = "sbrestore:v1:" + archive_digest[7:]
    body["archive_digest"] = archive_digest
    return RestoreArchiveManifestV1.model_validate(body)
