"""Machine-observed fixed provider surface inventory assembly."""

from __future__ import annotations

from typing import assert_never

from sb.effect_values import JsonInput, digest
from sb.provider_observation_models import (
    ProviderSurfaceInventoryV1,
    ProviderSurfaceObservationV1,
)
from sb.provider_surface_catalog import PROVIDER_SURFACE_CATALOG_DIGEST
from sb.provider_surface_files import scan_file_surface
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_special import (
    scan_fd_surface,
    scan_git_surface,
    scan_pointer_surface,
    scan_process_memory_surface,
)
from sb.provider_surface_specs import PROVIDER_SURFACE_SPECS

__all__ = ("ProviderSurfaceLayout", "scan_provider_surfaces")


def scan_provider_surfaces(
    layout: ProviderSurfaceLayout,
    needles: tuple[bytes, ...],
) -> ProviderSurfaceInventoryV1:
    entries: list[ProviderSurfaceObservationV1] = []
    for spec in PROVIDER_SURFACE_SPECS:
        match spec.scanner_kind:
            case "files" | "sqlite":
                entry = scan_file_surface(layout, spec, needles)
            case "git_objects" | "git_unreachable":
                entry = scan_git_surface(layout, spec, needles)
            case "pointer":
                entry = scan_pointer_surface(layout, spec)
            case "process_memory":
                entry = scan_process_memory_surface(layout, spec)
            case "fds":
                entry = scan_fd_surface(layout, spec, needles)
            case _:
                assert_never(spec.scanner_kind)
        entries.append(entry)
    entry_values = [entry.model_dump(mode="json") for entry in entries]
    body: dict[str, JsonInput] = {
        "schema_version": 1,
        "catalog_digest": PROVIDER_SURFACE_CATALOG_DIGEST,
        "expected_surface_count": 40,
        "observed_surface_count": len(entries),
        "omission_count": sum(entry.omission_count for entry in entries),
        "error_count": sum(entry.error_count for entry in entries),
        "match_count": sum(entry.match_count for entry in entries),
        "entries": entry_values,
    }
    return ProviderSurfaceInventoryV1.model_validate({
        **body,
        "manifest_digest": digest("surface", body),
    })
