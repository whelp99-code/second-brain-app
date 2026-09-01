"""Build proof-bound lifecycle observations from actual provider state."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from typing import assert_never

from sb.effect_values import JsonInput, digest
from sb.effect_write_models import CorrectionPayloadModelV2, MemoryEffectWriteRequestV2
from sb.effect_write_values import model_object
from sb.export_models import MemoryExportManifestV1
from sb.generations import Generation
from sb.provider_observation_models import (
    ProviderAbsenceObservationV1,
    ProviderArtifactObservationV1,
    ProviderExportObservationV1,
    ProviderLifecycleObservationsV1,
    ProviderSurfaceManifestV1,
)
from sb.provider_reingress_observations import observe_reingress_guards
from sb.provider_surface_scanner import ProviderSurfaceLayout, scan_provider_surfaces
from sb.reingress import ReingressGate


class ProviderObservationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderObservationInput:
    request: MemoryEffectWriteRequestV2
    generation: Generation
    layout: ProviderSurfaceLayout
    reingress: ReingressGate
    prior_needles: tuple[bytes, ...]
    export_manifest: MemoryExportManifestV1 | None
    created_at: str


def _artifact(input_: ProviderObservationInput) -> ProviderArtifactObservationV1:
    payload = input_.request.payload
    if not isinstance(payload, CorrectionPayloadModelV2):
        raise ProviderObservationError("PROVIDER_ARTIFACT_INVALID")
    target = input_.request.targets[0]
    relative = target.page_id if target.page_id.endswith(".md") else target.page_id + ".md"
    page = input_.generation.root / relative
    if not page.parent.resolve().is_relative_to(input_.generation.root.resolve()):
        raise ProviderObservationError("PROVIDER_ARTIFACT_INVALID")
    try:
        raw = page.read_bytes()
    except OSError as exc:
        raise ProviderObservationError("PROVIDER_ARTIFACT_INVALID") from exc
    replacement = payload.content.encode("utf-8")
    match_count = raw.count(replacement)
    if match_count != 1:
        raise ProviderObservationError("PROVIDER_ARTIFACT_INVALID")
    file_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    scan_digest = digest("surface", {
        "file_digest": file_digest,
        "byte_count": len(raw),
        "content_digest": payload.content_digest,
        "match_count": match_count,
    })
    body: dict[str, JsonInput] = {
        "target_manifest_digest": input_.request.target_manifest_digest,
        "generation_id": input_.generation.generation_id,
        "file_digest": file_digest,
        "file_count": 1,
        "byte_count": len(raw),
        "match_count": 1,
        "scan_digest": scan_digest,
    }
    return ProviderArtifactObservationV1.model_validate({
        **body,
        "manifest_digest": digest("surface", body),
    })


def _export(input_: ProviderObservationInput) -> ProviderExportObservationV1:
    manifest = input_.export_manifest
    if manifest is None:
        raise ProviderObservationError("PROVIDER_EXPORT_OBSERVATION_INVALID")
    records: list[dict[str, JsonInput]] = []
    byte_count = 0
    for declared in manifest.files:
        path = input_.layout.export_root / manifest.request_id / declared.name
        try:
            metadata = path.stat(follow_symlinks=False)
            raw = path.read_bytes()
        except OSError as exc:
            raise ProviderObservationError("PROVIDER_EXPORT_OBSERVATION_INVALID") from exc
        observed_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != declared.mode
            or len(raw) != declared.bytes
            or observed_digest != declared.digest
        ):
            raise ProviderObservationError("PROVIDER_EXPORT_OBSERVATION_INVALID")
        byte_count += len(raw)
        records.append({
            "file_digest": observed_digest,
            "byte_count": len(raw),
            "mode": stat.S_IMODE(metadata.st_mode),
        })
    if len(records) != len(manifest.files) or byte_count != manifest.data_bytes:
        raise ProviderObservationError("PROVIDER_EXPORT_OBSERVATION_INVALID")
    return ProviderExportObservationV1(
        manifest_digest=manifest.manifest_digest,
        file_count=len(records),
        byte_count=byte_count,
        record_count=manifest.record_count,
        scan_digest=digest("surface", {"files": records, "record_count": manifest.record_count}),
    )


def create_provider_observations(
    input_: ProviderObservationInput,
) -> ProviderLifecycleObservationsV1:
    inventory = scan_provider_surfaces(input_.layout, input_.prior_needles)
    guards = observe_reingress_guards(input_.reingress, input_.request, input_.prior_needles)
    if inventory.error_count or inventory.omission_count or inventory.match_count:
        raise ProviderObservationError("PROVIDER_SURFACE_INVENTORY_INCOMPLETE")
    if guards.error_count or guards.omission_count:
        raise ProviderObservationError("PROVIDER_REINGRESS_OBSERVATION_INCOMPLETE")
    manifest_body: dict[str, JsonInput] = {
        "schema_version": 1,
        "provider_instance_id": input_.request.provider_instance_id,
        "generation_id": input_.generation.generation_id,
        "generation_manifest_digest": input_.generation.manifest.generation_digest,
        "vault_head": input_.generation.head,
        "vault_tree": input_.generation.tree,
        "tombstone_sequence": input_.request.tombstone_high_water.sequence,
        "tombstone_set_root": input_.request.tombstone_high_water.set_root,
        "provider_inventory": model_object(inventory),
        "reingress_guards": model_object(guards),
        "created_at": input_.created_at,
    }
    surface_manifest = ProviderSurfaceManifestV1.model_validate({
        **manifest_body,
        "manifest_digest": digest("surface", manifest_body),
    })
    match input_.request.operation:
        case "correct":
            artifact = _artifact(input_)
            absence = ProviderAbsenceObservationV1(
                surface_manifest_digest=surface_manifest.manifest_digest,
                target_manifest_digest=input_.request.target_manifest_digest,
                match_count=0, error_count=0, omission_count=0,
                scan_digest=digest("surface", {
                    "inventory_manifest_digest": inventory.manifest_digest,
                    "target_manifest_digest": input_.request.target_manifest_digest,
                }),
            )
            export = None
        case "forget":
            artifact = None
            absence = ProviderAbsenceObservationV1(
                surface_manifest_digest=surface_manifest.manifest_digest,
                target_manifest_digest=input_.request.target_manifest_digest,
                match_count=0, error_count=0, omission_count=0,
                scan_digest=digest("surface", {
                    "inventory_manifest_digest": inventory.manifest_digest,
                    "target_manifest_digest": input_.request.target_manifest_digest,
                }),
            )
            export = None
        case "export":
            artifact = None
            absence = None
            export = _export(input_)
        case _:
            assert_never(input_.request.operation)
    body: dict[str, JsonInput] = {
        "schema_version": 1,
        "request_id": input_.request.request_id,
        "operation": input_.request.operation,
        "surface_manifest": model_object(surface_manifest),
        "artifact": None if artifact is None else model_object(artifact),
        "absence": None if absence is None else model_object(absence),
        "export": None if export is None else model_object(export),
    }
    return ProviderLifecycleObservationsV1.model_validate({
        **body,
        "observation_digest": digest("surface", body),
    })
