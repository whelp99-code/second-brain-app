"""Signed-fence exact-prefix non-activating restore sanitation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tarfile
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Final, final

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
from sb.restore_access import read_restore_access
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_knowledge import matching_restore_knowledge
from sb.restore_models import (
    RestoreArchiveManifestV1,
    RestoreProofV1,
    RestoreRequest,
    archive_file_digest,
    archive_locator,
    manifest_preimage,
)
from sb.restore_source import read_restore_knowledge
from sb.restore_workspace import restore_workspace
from sb.store.ledger import Ledger

_MAX_RESTORE_MEMBERS: Final = 100_000
_MAX_RESTORE_FILE_BYTES: Final = 64 * 1024 * 1024
_MAX_RESTORE_TOTAL_BYTES: Final = 10 * 1024 * 1024 * 1024


def _check_archive_budget(count: int, total: int, size: int) -> None:
    if (size < 0 or count > _MAX_RESTORE_MEMBERS
            or size > _MAX_RESTORE_FILE_BYTES or total > _MAX_RESTORE_TOTAL_BYTES):
        raise RestoreError("RESTORE_ARCHIVE_BUDGET_EXCEEDED")


class RestoreError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def _read_archive_file(source: Path, expected: os.stat_result) -> bytes:
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if _file_identity(before) != _file_identity(expected):
                raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(_MAX_RESTORE_FILE_BYTES + 1)
            if (_file_identity(os.fstat(descriptor)) != _file_identity(before)
                    or len(payload) != before.st_size):
                raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
            _check_archive_budget(1, len(payload), len(payload))
            return payload
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RestoreError("RESTORE_ARCHIVE_UNSAFE") from exc


@contextmanager
def _open_archive(source: Path) -> Generator[BinaryIO, None, None]:
    expected = source.stat(follow_symlinks=False)
    if not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1:
        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if _file_identity(os.fstat(descriptor)) != _file_identity(expected):
            raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            yield stream
        if (_file_identity(os.fstat(descriptor)) != _file_identity(expected)
                or _file_identity(source.stat(follow_symlinks=False)) != _file_identity(expected)):
            raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
    finally:
        os.close(descriptor)


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
        if workspace.is_symlink():
            raise RestoreError("RESTORE_WORKSPACE_UNSAFE")
        workspace.chmod(0o700)

    @staticmethod
    def _extract(archive: Path, destination: Path) -> None:
        if archive.is_dir() and not archive.is_symlink():
            sources: dict[Path, os.stat_result] = {}
            total = 0
            for source in archive.rglob("*"):
                metadata = source.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(metadata.st_mode)
                        or (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1)):
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                size = metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0
                total += size
                _check_archive_budget(len(sources) + 1, total, size)
                sources[source] = metadata
            for source in sorted(sources, key=lambda item: item.as_posix()):
                relative = source.relative_to(archive)
                if ".." in relative.parts:
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                metadata = source.stat(follow_symlinks=False)
                if _file_identity(metadata) != _file_identity(sources[source]):
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                target = destination / relative
                if stat.S_ISDIR(metadata.st_mode):
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    payload = _read_archive_file(source, metadata)
                    _ = target.write_bytes(payload)
                    target.chmod(stat.S_IMODE(metadata.st_mode))
                else:
                    raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
            return
        try:
            with _open_archive(archive) as source, tarfile.open(fileobj=source, mode="r:*") as bundle:
                members: list[tarfile.TarInfo] = []
                total = 0
                paths: dict[Path, bool] = {}
                for member in bundle:
                    size = member.size if member.isfile() else 0
                    total += size
                    _check_archive_budget(len(members) + 1, total, size)
                    members.append(member)
                    path = Path(member.name)
                    if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                    if not (member.isdir() or member.isfile()):
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                    if path in paths or (path == Path(".") and not member.isdir()):
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                    paths[path] = member.isdir()
                for path in paths:
                    if any(parent in paths and not paths[parent] for parent in path.parents):
                        raise RestoreError("RESTORE_ARCHIVE_UNSAFE")
                bundle.extractall(destination, members=members, filter="data")
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
        with restore_workspace(self.workspace, request_key) as staging:
            self._extract(request.archive, staging)
            self._verify_manifest(staging, request.archive_manifest)
            states = (read_restore_knowledge(staging, request.archive_manifest, mutations.store)
                      if (staging / "generation.json").is_file() else ())
            inventory = ManagedRestoreInventory().sanitize(staging, snapshot)
            knowledge = matching_restore_knowledge(states, inventory, snapshot)
            access = (read_restore_access(staging, request.archive_manifest, mutations.store, inventory, snapshot)
                      if (staging / "generation.json").is_file() else ())

            def materialize(root: Path) -> None:
                ManagedRestoreInventory.materialize(root, inventory)
                if knowledge or access:
                    with Ledger(root) as ledger, ledger.transaction():
                        for state in knowledge:
                            ledger.bind_knowledge(state)
                        for page in access:
                            for identity, requirement in page.sources:
                                ledger.bind_source_classification(identity, requirement)
                            ledger.bind_page_access(page.page_id, page.content_digest, page.requirements)

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
                    apply=materialize,
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
