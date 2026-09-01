"""Closed provider lifecycle observations retained behind the unchanged MCP contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sb.effect_write_models import ClosedModel
from sb.provider_surface_catalog import ProviderSurfaceOwner


class ProviderSurfaceObservationV1(ClosedModel):
    catalog_key: str
    owner: ProviderSurfaceOwner
    surface_id: str
    applicable: bool
    readable: bool
    manifest_digest: str
    file_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    object_count: int = Field(ge=0)
    fd_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    omission_count: int = Field(ge=0)
    scan_digest: str
    errors: list[str]


class ProviderSurfaceInventoryV1(ClosedModel):
    schema_version: Literal[1]
    catalog_digest: str
    manifest_digest: str
    expected_surface_count: Literal[40]
    observed_surface_count: Literal[40]
    omission_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    entries: list[ProviderSurfaceObservationV1] = Field(min_length=40, max_length=40)


class ReingressGuardObservationV1(ClosedModel):
    guard_id: str
    applicable: bool
    executed: bool
    blocked: bool
    error_code: str | None
    execution_count: int = Field(ge=0, le=1)
    error_count: int = Field(ge=0, le=1)
    omission_count: int = Field(ge=0, le=1)
    observation_digest: str


class ReingressGuardInventoryV1(ClosedModel):
    schema_version: Literal[1]
    catalog_digest: str
    manifest_digest: str
    expected_guard_count: Literal[10]
    observed_guard_count: Literal[10]
    error_count: int = Field(ge=0)
    omission_count: int = Field(ge=0)
    entries: list[ReingressGuardObservationV1] = Field(min_length=10, max_length=10)


class ProviderSurfaceManifestV1(ClosedModel):
    schema_version: Literal[1]
    manifest_digest: str
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: str
    vault_head: str
    vault_tree: str
    tombstone_sequence: int = Field(ge=0)
    tombstone_set_root: str
    provider_inventory: ProviderSurfaceInventoryV1
    reingress_guards: ReingressGuardInventoryV1
    created_at: str


class ProviderArtifactObservationV1(ClosedModel):
    manifest_digest: str
    target_manifest_digest: str
    generation_id: str
    file_digest: str
    file_count: Literal[1]
    byte_count: int = Field(ge=1)
    match_count: Literal[1]
    scan_digest: str


class ProviderAbsenceObservationV1(ClosedModel):
    surface_manifest_digest: str
    target_manifest_digest: str
    match_count: Literal[0]
    error_count: Literal[0]
    omission_count: Literal[0]
    scan_digest: str


class ProviderExportObservationV1(ClosedModel):
    manifest_digest: str
    file_count: int = Field(ge=1)
    byte_count: int = Field(ge=1)
    record_count: int = Field(ge=1)
    scan_digest: str


class ProviderLifecycleObservationsV1(ClosedModel):
    schema_version: Literal[1]
    observation_digest: str
    request_id: str
    operation: Literal["correct", "forget", "export"]
    surface_manifest: ProviderSurfaceManifestV1
    artifact: ProviderArtifactObservationV1 | None
    absence: ProviderAbsenceObservationV1 | None
    export: ProviderExportObservationV1 | None
