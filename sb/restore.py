"""Signed-fence exact-prefix non-activating restore sanitation."""

from __future__ import annotations

import hashlib
import shutil
import stat
import tarfile
from collections.abc import Mapping
from pathlib import Path
from tempfile import mkdtemp
from typing import final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.delegations import DelegationRejected, verify_read_fence
from sb.effect_values import JsonInput, digest
from sb.effect_write_values import model_object
from sb.generation_runtime import (
    GenerationAuthority,
    GenerationMutation,
    GenerationMutationService,
    GenerationOperation,
)
from sb.generations import Generation
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_models import (
    RestoreArchiveManifestV1,
    RestoreProofV1,
    RestoreRequest,
    archive_file_digest,
    archive_locator,
    manifest_preimage,
)


class RestoreError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class GenerationRestoreSanitizer:
    def __init__(
        self,
        workspace: Path,
        provider_instance_id: str,
        jarvis_public_keys: Mapping[str, Ed25519PublicKey],
    ) -> None:
        self.workspace = workspace
        self.provider_instance_id = provider_instance_id
        self.jarvis_public_keys = jarvis_public_keys
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace.chmod(0o700)

    @staticmethod
    def _extract(archive: Path, destination: Path) -> None:
        if archive.is_dir() and not archive.is_symlink():
            for source in sorted(archive.rglob("*"), key=lambda item: item.as_posix()):
                relative = source.relative_to(archive)
                if ".." in relative.parts:
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                metadata = source.stat(follow_symlinks=False)
                target = destination / relative
                if stat.S_ISDIR(metadata.st_mode):
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    _ = target.write_bytes(source.read_bytes())
                    target.chmod(stat.S_IMODE(metadata.st_mode))
                else:
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
            return
        try:
            with tarfile.open(archive, mode="r:*") as bundle:
                members = bundle.getmembers()
                for member in members:
                    path = Path(member.name)
                    if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                    if not (member.isdir() or member.isfile()):
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                bundle.extractall(destination, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise RestoreError("RESTORE_ARCHIVE_UNSAFE") from exc

    def _verify_manifest(
        self,
        root: Path,
        manifest: RestoreArchiveManifestV1,
    ) -> None:
        if manifest.provider_instance_id != self.provider_instance_id:
            raise RestoreError("RESTORE_ARCHIVE_INVALID")
        observed: list[dict[str, JsonInput]] = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            payload = path.read_bytes()
            observed.append(
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
        expected = [entry.model_dump(mode="json") for entry in manifest.entries]
        if observed != expected or digest("surface", {"entries": observed}) != manifest.surface_manifest_digest:
            raise RestoreError("RESTORE_ARCHIVE_INVALID")
        observed_digest = digest("generation", manifest_preimage(manifest))
        if (
            observed_digest != manifest.archive_digest
            or manifest.archive_id != "sbrestore:v1:" + observed_digest[7:]
        ):
            raise RestoreError("RESTORE_ARCHIVE_INVALID")

    def sanitize(
        self,
        request: RestoreRequest,
        mutations: GenerationMutationService,
    ) -> tuple[Generation, RestoreProofV1]:
        snapshot = mutations.requests.verified_tombstone_snapshot()
        try:
            fence = verify_read_fence(
                model_object(request.jarvis_fence),
                self.jarvis_public_keys,
                self.provider_instance_id,
                request.now,
                snapshot.sequence,
                snapshot.set_root,
            )
        except DelegationRejected as exc:
            raise RestoreError(str(exc)) from exc
        if fence.purpose != "memory_status" or fence.operation != "status":
            raise RestoreError("TOMBSTONE_FENCE_REQUIRED")
        source = mutations.requests.tombstone_root_at(
            request.archive_manifest.source_tombstone_sequence
        )
        if source != (
            request.archive_manifest.source_tombstone_sequence,
            request.archive_manifest.source_tombstone_set_root,
        ):
            raise RestoreError("TOMBSTONE_SET_STALE")
        request_key = hashlib.sha256(request.request_id.encode("utf-8")).hexdigest()
        staging = Path(mkdtemp(prefix=f"restore-{request_key}-", dir=self.workspace))
        try:
            self._extract(request.archive, staging)
            self._verify_manifest(staging, request.archive_manifest)
            inventory = ManagedRestoreInventory().sanitize(staging, snapshot)
            result = mutations.mutate(
                GenerationMutation(
                    mutation_id=request.request_id,
                    operation=GenerationOperation.RESTORE,
                    now=request.now,
                    authority=GenerationAuthority(
                        None,
                        (snapshot.sequence, snapshot.set_root),
                        activate=False,
                    ),
                    apply=lambda root: ManagedRestoreInventory.materialize(root, inventory),
                )
            )
            final_inventory = ManagedRestoreInventory().sanitize(
                result.generation.root, snapshot, require_clean=True
            )
            if final_inventory.blocked_matches != 0 or final_inventory.scan_errors != 0:
                raise RestoreError("RESTORE_SANITATION_FAILED")
            shutil.rmtree(staging)
            disposal = digest(
                "generation",
                {"archive_manifest_digest": request.archive_manifest.archive_digest, "disposed": True},
            )
            body: dict[str, JsonInput] = {
                "schema_version": 1,
                "request_id": request.request_id,
                "jarvis_fence_digest": fence.fence_digest,
                "chain_snapshot_digest": snapshot.snapshot_digest,
                "archive_manifest_digest": request.archive_manifest.archive_digest,
                "surface_manifest_digest": final_inventory.manifest_digest,
                "source_tombstone_sequence": source[0],
                "source_tombstone_set_root": source[1],
                "current_tombstone_sequence": snapshot.sequence,
                "current_tombstone_set_root": snapshot.set_root,
                "result_generation_id": result.generation.generation_id,
                "result_generation_digest": result.generation.manifest.generation_digest,
                "blocked_matches": 0,
                "scan_errors": 0,
                "staging_disposal_digest": disposal,
            }
            proof_digest = digest("generation", body)
            return result.generation, RestoreProofV1.model_validate(
                {**body, "proof_digest": proof_digest}
            )
        except (OSError, RuntimeError, ValueError):
            shutil.rmtree(staging, ignore_errors=True)
            raise
