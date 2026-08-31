"""Fixed-root record-level export publication, expiry, and invalidation.
# noqa: SIZE_OK -- one fixed-root export lifecycle boundary
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, final

from pydantic import Field

from sb.effect_values import (
    JsonInput,
    JsonObject,
    canonical_bytes,
    digest,
    format_instant,
    parse_instant,
    strict_loads,
)
from sb.effect_write_models import (
    ClosedModel,
    ExportPayloadModelV2,
    MemoryEffectWriteRequestV2,
    ResolvedMemoryTargetModel,
)
from sb.generations import Generation


class ExportError(RuntimeError):
    pass


class ExportFileV1(ClosedModel):
    name: Literal["memory.json"]
    digest: str
    mode: Literal[384]
    bytes: int


class MemoryExportManifestV1(ClosedModel):
    schema_version: Literal[1]
    manifest_id: str
    manifest_digest: str
    request_id: str
    request_digest: str
    delegation_id: str
    delegation_digest: str
    scope_digest: str
    provider_instance_id: str
    provider_release_sha: str
    generation_id: str
    vault_head: str
    vault_tree: str
    tombstone_sequence: int
    tombstone_set_root: str
    target_ids: list[str] = Field(min_length=1, max_length=64)
    source_identities: list[str] = Field(min_length=1, max_length=64)
    content_identities: list[str] = Field(min_length=1, max_length=64)
    citation_identities: list[str] = Field(min_length=1, max_length=64)
    sensitivity_classes: list[str]
    valid_from: str
    valid_until: str
    record_count: int
    data_bytes: int
    files: list[ExportFileV1] = Field(min_length=1, max_length=1)
    created_at: str
    expires_at: str


@final
class ExportPublisher:
    def __init__(self, root: Path, provider_release_sha: str) -> None:
        self.root = root
        self.provider_release_sha = provider_release_sha
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = root.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink < 2
        ):
            raise ExportError("EXPORT_ROOT_UNSAFE")
        root.chmod(0o700)

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise ExportError("WRITE_REQUEST_IO_FAILED")
                written += count
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ExportError("EXPORT_ROOT_UNSAFE")
        finally:
            os.close(descriptor)

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

    def publish(
        self,
        request: MemoryEffectWriteRequestV2,
        generation: Generation,
        now: datetime,
        *,
        current_high_water: Callable[[], tuple[int, str]],
        fence: int,
    ) -> MemoryExportManifestV1:
        payload = request.payload
        if request.operation != "export" or not isinstance(payload, ExportPayloadModelV2):
            raise ExportError("EFFECT_OPERATION_CONFUSION")
        if current_high_water() != (
            request.tombstone_high_water.sequence,
            request.tombstone_high_water.set_root,
        ):
            raise ExportError("TOMBSTONE_SET_STALE")
        records = [self._record(generation, target) for target in request.targets]
        data = canonical_bytes({"schema_version": 1, "records": records}) + b"\n"
        if len(records) > payload.max_records or len(data) > payload.max_bytes:
            raise ExportError("EXPORT_SCOPE_AMBIGUOUS")
        final = self.root / request.request_id
        if final.exists() or final.is_symlink():
            metadata = final.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            return self.read_manifest(request.request_id)
        staging = self.root / f".staging-{request.request_id}.{fence}"
        if staging.exists() or staging.is_symlink():
            metadata = staging.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            self._write(staging / "memory.json", data)
            file_row = ExportFileV1(
                name="memory.json",
                digest="sha256:" + hashlib.sha256(data).hexdigest(),
                mode=0o600,
                bytes=len(data),
            )
            expires = now + timedelta(days=1)
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
                "record_count": len(records),
                "data_bytes": len(data),
                "files": [file_row.model_dump(mode="json")],
                "created_at": format_instant(now),
                "expires_at": format_instant(expires),
            }
            observed = digest("export", body)
            body["manifest_id"] = "sbexport:v1:" + observed[7:]
            body["manifest_digest"] = observed
            manifest = MemoryExportManifestV1.model_validate(body)
            self._write(staging / "manifest.json", canonical_bytes(manifest.model_dump(mode="json")) + b"\n")
            if current_high_water() != (
                request.tombstone_high_water.sequence,
                request.tombstone_high_water.set_root,
            ):
                raise ExportError("TOMBSTONE_SET_STALE")
            if final.exists() or final.is_symlink():
                raise ExportError("WRITE_REQUEST_REPLAY_CONFLICT")
            os.rename(staging, final)
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
            return manifest
        except (OSError, RuntimeError, ValueError):
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def read_manifest(self, request_id: str) -> MemoryExportManifestV1:
        if "/" in request_id or ".." in request_id:
            raise ExportError("EXPORT_ROOT_UNSAFE")
        path = self.root / request_id / "manifest.json"
        value = strict_loads(path.read_bytes(), 262_144)
        return MemoryExportManifestV1.model_validate(value)

    def validate(self, now: datetime) -> None:
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            metadata = path.stat(follow_symlinks=False)
            if (
                path.name.startswith(".staging-")
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")
            names = {item.name for item in path.iterdir()}
            if names != {"memory.json", "manifest.json"}:
                raise ExportError("EXPORT_ROOT_UNSAFE")
            manifest = self.read_manifest(path.name)
            if manifest.request_id != path.name or parse_instant(manifest.expires_at) <= now:
                raise ExportError("EXPORT_ROOT_UNSAFE")
            data = path / "memory.json"
            data_metadata = data.stat(follow_symlinks=False)
            manifest_metadata = (path / "manifest.json").stat(follow_symlinks=False)
            if any(
                not stat.S_ISREG(item.st_mode)
                or item.st_uid != os.getuid()
                or item.st_nlink != 1
                or stat.S_IMODE(item.st_mode) != 0o600
                for item in (data_metadata, manifest_metadata)
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")
            raw = data.read_bytes()
            expected = manifest.files[0]
            if (
                expected.name != "memory.json"
                or expected.bytes != len(raw)
                or expected.digest != "sha256:" + hashlib.sha256(raw).hexdigest()
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")

    def expire(self, now: datetime) -> tuple[str, ...]:
        removed: list[str] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".staging-"):
                shutil.rmtree(path)
                removed.append(hashlib.sha256(path.name.encode()).hexdigest())
                continue
            if not path.is_dir() or path.is_symlink():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            manifest = self.read_manifest(path.name)
            if parse_instant(manifest.expires_at) <= now:
                shutil.rmtree(path)
                removed.append(hashlib.sha256(path.name.encode()).hexdigest())
        return tuple(removed)

    def invalidate(self, identities: set[str]) -> tuple[str, ...]:
        removed: list[str] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".staging-"):
                shutil.rmtree(path)
                continue
            manifest = self.read_manifest(path.name)
            managed_identities = {
                *manifest.target_ids,
                *manifest.source_identities,
                *manifest.content_identities,
                *manifest.citation_identities,
            }
            if identities.intersection(managed_identities):
                shutil.rmtree(path)
                removed.append(hashlib.sha256(path.name.encode()).hexdigest())
        return tuple(removed)
