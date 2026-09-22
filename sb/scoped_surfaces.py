"""Shared authorization checks for scoped export and restore surfaces.

The MCP read profiles own transport and claim decoding.  Export manifests and
restore archives are deliberately separate value objects, so their callers use
these checks after decoding the same signed claim and read fence.  Keeping the
checks here prevents either surface from treating a historical digest as
current authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.access_claims import AccessContext, access_request_digest, verify_access_claim
from sb.effect_values import JsonValue, parse_instant
from sb.export_models import MemoryExportManifestV1
from sb.restore_access import RestorePageAccess
from sb.restore_models import RestoreArchiveManifestV1
from sb.source_access import SourceAccess


class ScopedSurfaceRejected(ValueError):
    """A scoped surface cannot be used under the supplied current authority."""


def authorize_export(
    manifest: MemoryExportManifestV1,
    *,
    read_fence: JsonValue,
    access_claim: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    context: AccessContext,
    now: datetime,
    current_high_water: tuple[int, str],
    generation_id: str,
) -> SourceAccess:
    """Authorize an export manifest before exposing bytes or a download handle.

    The claim is bound to the caller's exact request by ``context``.  The
    manifest is then checked against the same provider, generation, and
    deletion high-water.  A valid old signature therefore cannot resurrect an
    expired or deleted export.
    """
    if context.purpose != "memory_status":
        raise ScopedSurfaceRejected("MEMORY_SCOPED_EXPORT_DENIED")
    if context.request_digest != access_request_digest(
        "sb_export",
        {"request_id": manifest.request_id, "manifest_digest": manifest.manifest_digest},
    ):
        raise ScopedSurfaceRejected("MEMORY_SCOPED_EXPORT_DENIED")
    scope = verify_access_claim(access_claim, read_fence, keys, context, now)
    if (
        manifest.provider_instance_id != context.provider
        or manifest.generation_id != generation_id
        or (manifest.tombstone_sequence, manifest.tombstone_set_root) != current_high_water
    ):
        raise ScopedSurfaceRejected("MEMORY_SCOPED_EXPORT_DENIED")
    if parse_instant(manifest.expires_at) <= now:
        raise ScopedSurfaceRejected("MEMORY_SCOPED_EXPORT_DENIED")
    return scope


def authorize_restore(
    archive: RestoreArchiveManifestV1,
    *,
    read_fence: JsonValue,
    access_claim: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    context: AccessContext,
    now: datetime,
    current_high_water: tuple[int, str],
) -> SourceAccess:
    """Authorize a restore archive before its contents are materialized."""
    if context.purpose != "memory_status":
        raise ScopedSurfaceRejected("MEMORY_SCOPED_RESTORE_DENIED")
    if context.request_digest != access_request_digest(
        "sb_restore", {"archive_id": archive.archive_id}
    ):
        raise ScopedSurfaceRejected("MEMORY_SCOPED_RESTORE_DENIED")
    scope = verify_access_claim(access_claim, read_fence, keys, context, now)
    if archive.provider_instance_id != context.provider:
        raise ScopedSurfaceRejected("MEMORY_SCOPED_RESTORE_DENIED")
    source_high_water = (
        archive.source_tombstone_sequence,
        archive.source_tombstone_set_root,
    )
    if source_high_water[0] > current_high_water[0] or (
        source_high_water[0] == current_high_water[0]
        and source_high_water[1] != current_high_water[1]
    ):
        raise ScopedSurfaceRejected("MEMORY_SCOPED_RESTORE_DENIED")
    return scope


def require_restore_scope(
    pages: tuple[RestorePageAccess, ...], scope: SourceAccess
) -> None:
    """Apply the current membership scope to every restored classified page."""
    for page in pages:
        for _identity, requirement in page.sources:
            if (
                requirement.owner != scope.owner
                or requirement.policy_revision != scope.policy_revision
                or (not requirement.projects and bool(scope.projects))
                or not set(requirement.projects) <= set(scope.projects)
            ):
                raise ScopedSurfaceRejected("MEMORY_SCOPED_RESTORE_DENIED")
