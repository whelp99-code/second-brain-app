"""Closed fixed-root export manifest models and constants."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from sb.effect_write_models import ClosedModel

EXPORT_RETENTION_MS: Final = 86_400_000


class ExportError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
