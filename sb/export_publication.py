"""Durable fixed-root export construction and atomic publication."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import final

from sb.effect_values import (
    JsonInput,
    JsonObject,
    canonical_bytes,
    digest,
    format_instant,
    parse_instant,
)
from sb.effect_write_models import (
    ExportPayloadModelV2,
    MemoryEffectWriteRequestV2,
    ResolvedMemoryTargetModel,
)
from sb.export_files import directory_fsync, no_barrier, read_manifest, write_private
from sb.export_journal import ExportJournal, ExportLifecycleRecord
from sb.export_models import (
    EXPORT_RETENTION_MS,
    ExportError,
    ExportFileV1,
    MemoryExportManifestV1,
)
from sb.generations import Generation


@dataclass(frozen=True, slots=True)
class ExportPublication:
    request: MemoryEffectWriteRequestV2
    generation: Generation
    now: datetime
    current_high_water: Callable[[], tuple[int, str]]
    fence: int
    barrier: Callable[[str], None] | None = None


@dataclass(frozen=True, slots=True)
class ExportStaging:
    publication: ExportPublication
    root: Path
    data: bytes
    records: tuple[JsonObject, ...]


@final
class ExportPublicationService:
    def __init__(
        self,
        root: Path,
        provider_release_sha: str,
        journal: ExportJournal,
    ) -> None:
        self.root = root
        self.provider_release_sha = provider_release_sha
        self.journal = journal

    @staticmethod
    def _record(generation: Generation, target: ResolvedMemoryTargetModel) -> JsonObject:
        if (
            target.generation_id != generation.generation_id
            or target.vault_head != generation.head
            or target.vault_tree != generation.tree
        ):
            raise ExportError("EFFECT_PRIOR_STALE")
        path = generation.root / (target.page_id + ".md")
        body = path.read_bytes()
        if "sha256:" + hashlib.sha256(body).hexdigest() != target.page_content_digest:
            raise ExportError("EFFECT_PRIOR_STALE")
        start, end = target.citation_span_start, target.citation_span_end
        if not 0 <= start < end <= len(body):
            raise ExportError("EXPORT_SCOPE_AMBIGUOUS")
        record = body[start:end]
        if hashlib.sha256(record).hexdigest() != target.content_identity_full:
            raise ExportError("EXPORT_SCOPE_AMBIGUOUS")
        try:
            content = record.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExportError("EXPORT_SCOPE_AMBIGUOUS") from exc
        return {
            "target_id": target.target_id,
            "source_identity_full": target.source_identity_full,
            "content_identity_full": target.content_identity_full,
            "citation_identity_full": target.citation_identity_full,
            "sensitivity": target.sensitivity,
            "valid_from": target.valid_from,
            "valid_until": target.valid_until,
            "content": content,
        }

    def publish(self, publication: ExportPublication) -> MemoryExportManifestV1:
        request = publication.request
        generation = publication.generation
        now = publication.now
        emit = publication.barrier or no_barrier
        payload = request.payload
        if request.operation != "export" or not isinstance(payload, ExportPayloadModelV2):
            raise ExportError("EFFECT_OPERATION_CONFUSION")
        expected_high_water = (
            request.tombstone_high_water.sequence,
            request.tombstone_high_water.set_root,
        )
        if publication.current_high_water() != expected_high_water:
            raise ExportError("TOMBSTONE_SET_STALE")
        records = tuple(self._record(generation, target) for target in request.targets)
        data = canonical_bytes({"schema_version": 1, "records": list(records)}) + b"\n"
        if len(records) > payload.max_records or len(data) > payload.max_bytes:
            raise ExportError("EXPORT_SCOPE_AMBIGUOUS")
        final = self.root / request.request_id
        if final.exists() or final.is_symlink():
            metadata = final.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            record = self.journal.get(request.request_id)
            if (
                record is None
                or record.state != "available"
                or parse_instant(record.expires_at) <= now
            ):
                raise ExportError("EXPORT_EXPIRED")
            return read_manifest(self.root, request.request_id)
        staging = self.root / f".staging-{request.request_id}.{publication.fence}"
        if staging.exists() or staging.is_symlink():
            metadata = staging.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        directory_fsync(self.root)
        emit("successor_creation")
        intent_recorded = False
        try:
            manifest = self._seal(ExportStaging(publication, staging, data, records))
            emit("sealed_manifest")
            _ = self.journal.publishing(
                ExportLifecycleRecord(
                    request.request_id,
                    manifest.manifest_digest,
                    generation.generation_id,
                    request.tombstone_high_water.sequence,
                    request.tombstone_high_water.set_root,
                    manifest.created_at,
                    manifest.expires_at,
                    "publishing",
                    None,
                    0,
                    None,
                    None,
                    manifest.created_at,
                )
            )
            intent_recorded = True
            emit("switch_intent_fsync")
            if publication.current_high_water() != expected_high_water:
                raise ExportError("TOMBSTONE_SET_STALE")
            if final.exists() or final.is_symlink():
                raise ExportError("WRITE_REQUEST_REPLAY_CONFLICT")
            os.rename(staging, final)
            emit("pointer_rename")
            directory_fsync(self.root)
            emit("pointer_parent_fsync")
            _ = self.journal.available(request.request_id, now)
            if read_manifest(self.root, request.request_id) != manifest:
                raise ExportError("EXPORT_ROOT_UNSAFE")
            emit("activation_verify")
            return manifest
        except (OSError, RuntimeError, ValueError):
            if not intent_recorded:
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def _seal(self, staging: ExportStaging) -> MemoryExportManifestV1:
        publication = staging.publication
        emit = publication.barrier or no_barrier
        request = publication.request
        generation = publication.generation
        payload = request.payload
        if not isinstance(payload, ExportPayloadModelV2):
            raise ExportError("EFFECT_OPERATION_CONFUSION")
        write_private(staging.root / "memory.json", staging.data)
        for barrier in (
            "sanitized_copy",
            "git_seal",
            "ledger_build",
            "lexical_build",
            "vector_build",
            "brief_build",
        ):
            emit(barrier)
        file_row = ExportFileV1(
            name="memory.json",
            digest="sha256:" + hashlib.sha256(staging.data).hexdigest(),
            mode=0o600,
            bytes=len(staging.data),
        )
        expires = publication.now + timedelta(milliseconds=EXPORT_RETENTION_MS)
        body: dict[str, JsonInput] = {
            "schema_version": 1,
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "delegation_id": request.delegation.delegation_id,
            "delegation_digest": request.delegation.delegation_digest,
            "scope_digest": request.scope_digest,
            "provider_instance_id": request.provider_instance_id,
            "provider_release_sha": self.provider_release_sha,
            "generation_id": generation.generation_id,
            "vault_head": generation.head,
            "vault_tree": generation.tree,
            "tombstone_sequence": request.tombstone_high_water.sequence,
            "tombstone_set_root": request.tombstone_high_water.set_root,
            "target_ids": [target.target_id for target in request.targets],
            "source_identities": [target.source_identity_full for target in request.targets],
            "content_identities": [target.content_identity_full for target in request.targets],
            "citation_identities": [target.citation_identity_full for target in request.targets],
            "sensitivity_classes": payload.sensitivity_classes,
            "valid_from": payload.valid_from,
            "valid_until": payload.valid_until,
            "record_count": len(staging.records),
            "data_bytes": len(staging.data),
            "files": [file_row.model_dump(mode="json")],
            "created_at": format_instant(publication.now),
            "expires_at": format_instant(expires),
        }
        observed = digest("export", body)
        body["manifest_id"] = "sbexport:v1:" + observed[7:]
        body["manifest_digest"] = observed
        manifest = MemoryExportManifestV1.model_validate(body)
        write_private(
            staging.root / "manifest.json",
            canonical_bytes(manifest.model_dump(mode="json")) + b"\n",
        )
        directory_fsync(staging.root)
        return manifest
