"""High-water-gated backup/import restore sanitizer and proof seam."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

from sb.effect_values import JsonValue, digest
from sb.erasure import scan_managed_surfaces
from sb.generations import Generation, GenerationStore


class RestoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RestoreProofV1:
    input_digest: str
    source_tombstone_sequence: int
    source_tombstone_set_root: str
    current_tombstone_sequence: int
    current_tombstone_set_root: str
    result_generation_id: str
    result_generation_digest: str
    sentinel_matches: int
    scan_errors: int
    staging_disposal_digest: str
    proof_digest: str


@final
class GenerationRestoreSanitizer:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
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
                    target.chmod(0o600)
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

    @staticmethod
    def _input_digest(root: Path) -> str:
        rows: list[dict[str, JsonValue]] = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                raw = path.read_bytes()
                rows.append(
                    {
                        "id": hashlib.sha256(path.relative_to(root).as_posix().encode()).hexdigest(),
                        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw),
                    }
                )
        return digest("generation", {"restore_input": rows})

    def sanitize(
        self,
        *,
        archive: Path,
        store: GenerationStore,
        source_high_water: tuple[int, str],
        current_high_water: tuple[int, str],
        forbidden_needles: tuple[bytes, ...],
        now: datetime,
        request_id: str,
        activate: bool = False,
    ) -> tuple[Generation, RestoreProofV1]:
        source_sequence, source_root = source_high_water
        current_sequence, current_root = current_high_water
        if source_sequence > current_sequence:
            raise RestoreError("TOMBSTONE_SET_STALE")
        if source_sequence == current_sequence and source_root != current_root:
            raise RestoreError("TOMBSTONE_SET_STALE")
        staging = self.workspace / f"restore-{request_id}.{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            self._extract(archive, staging)
            input_digest = self._input_digest(staging)
            for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix(), reverse=True):
                if path.is_file() and any(needle in path.read_bytes() for needle in forbidden_needles):
                    path.unlink()
            active: Generation | None
            try:
                active = store.active()
            except RuntimeError:
                active = None

            def allowed(relative: Path) -> bool:
                del relative
                return False

            def materialize(destination: Path) -> None:
                for source in sorted(staging.rglob("*"), key=lambda item: item.as_posix()):
                    relative = source.relative_to(staging)
                    if relative.parts and relative.parts[0] in {".git", ".sb"}:
                        continue
                    target = destination / relative
                    if source.is_dir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    elif source.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        _ = target.write_bytes(source.read_bytes())
                        target.chmod(0o600)

            generation = store.build(
                request_id=request_id,
                parent=active,
                tombstone_sequence=current_sequence,
                tombstone_set_root=current_root,
                created_at=now,
                allowed=allowed,
                mutate=materialize,
            )
            inventory = scan_managed_surfaces((generation.root,), forbidden_needles)
            if inventory.scan_errors or inventory.matches:
                raise RestoreError("RESTORE_SANITATION_FAILED")
            if activate:
                store.activate(generation, active, now)
            shutil.rmtree(staging)
            disposal = digest("generation", {"restore_staging": input_digest, "disposed": True})
            proof_body = {
                "input_digest": input_digest,
                "source_tombstone_sequence": source_sequence,
                "source_tombstone_set_root": source_root,
                "current_tombstone_sequence": current_sequence,
                "current_tombstone_set_root": current_root,
                "result_generation_id": generation.generation_id,
                "result_generation_digest": generation.manifest.generation_digest,
                "sentinel_matches": inventory.matches,
                "scan_errors": inventory.scan_errors,
                "staging_disposal_digest": disposal,
            }
            proof = RestoreProofV1(
                input_digest=input_digest,
                source_tombstone_sequence=source_sequence,
                source_tombstone_set_root=source_root,
                current_tombstone_sequence=current_sequence,
                current_tombstone_set_root=current_root,
                result_generation_id=generation.generation_id,
                result_generation_digest=generation.manifest.generation_digest,
                sentinel_matches=inventory.matches,
                scan_errors=inventory.scan_errors,
                staging_disposal_digest=disposal,
                proof_digest=digest("generation", proof_body),
            )
            return generation, proof
        except (OSError, RuntimeError, ValueError):
            shutil.rmtree(staging, ignore_errors=True)
            raise
