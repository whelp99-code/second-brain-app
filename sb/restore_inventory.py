"""Fixed exhaustive restore inventory with identity-derived sanitation."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, final

from sb.effect_values import JsonInput, digest
from sb.restore_models import archive_file_digest, archive_locator
from sb.tombstone_snapshot import BlockedTargetIdentity, TombstoneSnapshot

SurfaceClass = Literal[
    "wiki",
    "daily",
    "conflicts",
    "log",
    "raw_cas",
    "inbox",
    "derived_sqlite",
    "git",
    "generation_manifest",
]

RESTORE_SURFACE_CLASSES: Final[tuple[SurfaceClass, ...]] = (
    "wiki",
    "daily",
    "conflicts",
    "log",
    "raw_cas",
    "inbox",
    "derived_sqlite",
    "git",
    "generation_manifest",
)


class RestoreInventoryError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SanitizedRestoreFile:
    relative: Path
    payload: bytes


@dataclass(frozen=True, slots=True)
class RestoreInventoryResult:
    files: tuple[SanitizedRestoreFile, ...]
    manifest_digest: str
    blocked_matches: Literal[0]
    scan_errors: Literal[0]


def _surface(relative: Path) -> SurfaceClass:
    first = relative.parts[0]
    if first == "wiki":
        return "wiki"
    if first == "daily":
        return "daily"
    if first == "conflicts":
        return "conflicts"
    if relative == Path("log.md"):
        return "log"
    if first == "raw":
        return "raw_cas"
    if first == "inbox" and not {".done", ".requests"}.intersection(relative.parts):
        return "inbox"
    if first == ".sb":
        return "derived_sqlite"
    if first == ".git":
        return "git"
    if relative == Path("generation.json") or relative == Path(".gitignore"):
        return "generation_manifest"
    raise RestoreInventoryError("RESTORE_INVENTORY_INCOMPLETE")


def _page_id(relative: Path) -> str | None:
    if relative.suffix != ".md" or relative.parts[0] not in {"wiki", "daily", "conflicts"}:
        return None
    return relative.with_suffix("").as_posix()


def _sanitize_markdown(
    relative: Path,
    payload: bytes,
    targets: tuple[BlockedTargetIdentity, ...],
) -> bytes:
    page_id = _page_id(relative)
    if page_id is None:
        return payload
    page_digest = "sha256:" + hashlib.sha256(page_id.encode("utf-8")).hexdigest()
    matches = [target for target in targets if target.page_id_digest == page_digest]
    intervals: list[tuple[int, int]] = []
    for target in matches:
        start = target.citation_span_start
        end = target.citation_span_end
        exact_source = "sha256:" + hashlib.sha256(payload).hexdigest() == target.page_content_digest
        record_matches = (
            0 <= start < end <= len(payload)
            and hashlib.sha256(payload[start:end]).hexdigest() == target.content_identity_digest
        )
        if not exact_source and not record_matches:
            continue
        if not record_matches:
            raise RestoreInventoryError("RESTORE_SANITATION_FAILED")
        line_start = payload.rfind(b"\n", 0, start) + 1
        # end is exclusive: a terminating newline already belongs to this span.
        next_newline = payload.find(b"\n", end - 1)
        line_end = len(payload) if next_newline < 0 else next_newline + 1
        intervals.append((line_start, line_end))
    # All offsets refer to the original bytes. Merge overlapping line removals
    # before editing so repeated tombstones cannot consume surviving memory.
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    result = payload
    for start, end in reversed(merged):
        result = result[:start] + result[end:]
    return result


def _is_whole_blocked(payload: bytes, targets: tuple[BlockedTargetIdentity, ...]) -> bool:
    observed = hashlib.sha256(payload).hexdigest()
    return any(observed == target.content_identity_digest for target in targets)


@final
class ManagedRestoreInventory:
    """Classify every archive file through one immutable registry."""

    def sanitize(self, extracted: Path, snapshot: TombstoneSnapshot) -> RestoreInventoryResult:
        counts: dict[SurfaceClass, int] = {surface: 0 for surface in RESTORE_SURFACE_CLASSES}
        files: list[SanitizedRestoreFile] = []
        seen: list[dict[str, JsonInput]] = []
        for path in sorted(extracted.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(extracted)
            surface = _surface(relative)
            counts[surface] += 1
            payload = path.read_bytes()
            seen.append(
                {
                    "surface": surface,
                    "locator_digest": archive_locator(relative),
                    "file_digest": archive_file_digest(payload),
                }
            )
            if surface in {"derived_sqlite", "git", "generation_manifest"}:
                continue
            if _is_whole_blocked(payload, snapshot.targets):
                continue
            sanitized = _sanitize_markdown(relative, payload, snapshot.targets)
            if _is_whole_blocked(sanitized, snapshot.targets):
                raise RestoreInventoryError("RESTORE_SANITATION_FAILED")
            files.append(SanitizedRestoreFile(relative, sanitized))
        rows = [
            {"surface": surface, "file_count": counts[surface]}
            for surface in RESTORE_SURFACE_CLASSES
        ]
        return RestoreInventoryResult(
            files=tuple(files),
            manifest_digest=digest("surface", {"inventory": rows, "observed": seen}),
            blocked_matches=0,
            scan_errors=0,
        )

    @staticmethod
    def materialize(destination: Path, result: RestoreInventoryResult) -> None:
        for child in tuple(destination.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for item in result.files:
            target = destination / item.relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _ = target.write_bytes(item.payload)
            target.chmod(0o600)
