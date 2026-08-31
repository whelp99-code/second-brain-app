"""Permanent tombstone reingress gates and managed-copy generation sanitation."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast, final

from sb.effect_values import canonical_bytes, digest, format_instant
from sb.effect_write_models import CorrectionPayloadModelV2, MemoryEffectWriteRequestV2


class ErasureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SurfaceInventoryEntry:
    owner: str
    surface_id: str
    manifest_digest: str
    readable: bool
    file_count: int
    row_count: int
    object_count: int
    fd_count: int
    scan_digest: str
    matches: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfaceInventory:
    entries: tuple[SurfaceInventoryEntry, ...]
    manifest_digest: str
    scan_errors: int
    matches: int


@final
class ReingressGate:
    """Persist blocked stable source/subject identities before every ingress write."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None)
        _ = self.db.execute("PRAGMA journal_mode=DELETE")
        _ = self.db.execute("PRAGMA synchronous=FULL")
        _ = self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS blocked_identities(
              identity_kind TEXT NOT NULL CHECK(identity_kind IN ('source','subject','content','citation')),
              identity_digest TEXT NOT NULL,
              tombstone_sequence INTEGER NOT NULL,
              tombstone_set_root TEXT NOT NULL,
              blocked_at TEXT NOT NULL,
              PRIMARY KEY(identity_kind,identity_digest)
            );
            CREATE TABLE IF NOT EXISTS new_version_exceptions(
              source_identity_digest TEXT NOT NULL,
              content_identity_digest TEXT NOT NULL,
              authority_digest TEXT NOT NULL UNIQUE,
              approved_at TEXT NOT NULL,
              PRIMARY KEY(source_identity_digest,content_identity_digest)
            );
            CREATE TRIGGER IF NOT EXISTS blocked_no_update BEFORE UPDATE ON blocked_identities
              BEGIN SELECT RAISE(ABORT,'immutable blocked identity'); END;
            CREATE TRIGGER IF NOT EXISTS blocked_no_delete BEFORE DELETE ON blocked_identities
              BEGIN SELECT RAISE(ABORT,'immutable blocked identity'); END;
            """
        )
        path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def block_request(self, request: MemoryEffectWriteRequestV2, now: datetime) -> None:
        if request.operation not in {"correct", "forget"}:
            return
        rows: list[tuple[str, str, int, str, str]] = []
        for target in request.targets:
            rows.extend(
                (
                    (
                        "source",
                        target.source_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root,
                        format_instant(now),
                    ),
                    (
                        "content",
                        target.content_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root,
                        format_instant(now),
                    ),
                    (
                        "citation",
                        target.citation_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root,
                        format_instant(now),
                    ),
                    (
                        "subject",
                        target.subject_digest,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root,
                        format_instant(now),
                    ),
                )
            )
        _ = self.db.executemany(
            "INSERT OR IGNORE INTO blocked_identities VALUES(?,?,?,?,?)",
            rows,
        )

    def check(
        self,
        *,
        source_identity: str,
        content_identity: str,
        subject_identity: str | None = None,
        citation_identity: str | None = None,
    ) -> None:
        checks = [
            ("source", source_identity),
            ("content", content_identity),
        ]
        if subject_identity is not None:
            checks.append(("subject", subject_identity))
        if citation_identity is not None:
            checks.append(("citation", citation_identity))
        blocked = False
        for kind, identity in checks:
            row = cast(
                tuple[int] | None,
                self.db.execute(
                    "SELECT 1 FROM blocked_identities WHERE identity_kind=? AND identity_digest=?",
                    (kind, identity),
                ).fetchone(),
            )
            blocked = blocked or row is not None
        if not blocked:
            return
        exception = cast(
            tuple[int] | None,
            self.db.execute(
                "SELECT 1 FROM new_version_exceptions WHERE source_identity_digest=? AND content_identity_digest=?",
                (source_identity, content_identity),
            ).fetchone(),
        )
        if exception is None:
            raise ErasureError("TOMBSTONE_REINGRESS_BLOCKED")

    def allow_new_version(
        self,
        source_identity: str,
        content_identity: str,
        authority_digest: str,
        now: datetime,
    ) -> None:
        _ = self.db.execute(
            "INSERT INTO new_version_exceptions VALUES(?,?,?,?)",
            (source_identity, content_identity, authority_digest, format_instant(now)),
        )


@final
class ErasureEngine:
    def __init__(self, reingress: ReingressGate) -> None:
        self.reingress = reingress

    @staticmethod
    def _page(root: Path, page_id: str) -> Path:
        relative = page_id if page_id.endswith(".md") else page_id + ".md"
        path = root / relative
        resolved_parent = path.parent.resolve()
        if not resolved_parent.is_relative_to(root.resolve()):
            raise ErasureError("EFFECT_TARGET_INVALID")
        return path

    @staticmethod
    def _write_private(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            written = 0
            while written < len(value):
                count = os.write(descriptor, value[written:])
                if count <= 0:
                    raise ErasureError("GENERATION_WRITE_FAILED")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    def apply(self, root: Path, request: MemoryEffectWriteRequestV2, now: datetime) -> tuple[str, ...]:
        if request.operation == "export":
            return ()
        removed: list[str] = []
        prior_records: list[bytes] = []
        for index, target in enumerate(request.targets):
            page = self._page(root, target.page_id)
            try:
                body = page.read_bytes()
            except OSError as exc:
                raise ErasureError("EFFECT_PRIOR_STALE") from exc
            observed = "sha256:" + hashlib.sha256(body).hexdigest()
            if observed != target.page_content_digest:
                raise ErasureError("EFFECT_PRIOR_STALE")
            start, end = target.citation_span_start, target.citation_span_end
            if not 0 <= start < end <= len(body):
                raise ErasureError("EFFECT_TARGET_INVALID")
            prior = body[start:end]
            if hashlib.sha256(prior).hexdigest() != target.content_identity_full:
                raise ErasureError("EFFECT_TARGET_INVALID")
            prior_records.append(prior)
            if request.operation == "correct" and index == 0:
                payload = request.payload
                if not isinstance(payload, CorrectionPayloadModelV2):
                    raise ErasureError("EFFECT_OPERATION_CONFUSION")
                successor = body[:start] + payload.content.encode("utf-8") + body[end:]
            else:
                successor = body[:start] + body[end:]
            self._write_private(page, successor)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or ".git" in path.relative_to(root).parts:
                continue
            if path in {self._page(root, target.page_id) for target in request.targets}:
                continue
            try:
                body = path.read_bytes()
            except OSError as exc:
                raise ErasureError("SURFACE_SCAN_FAILED") from exc
            if any(prior in body for prior in prior_records):
                relative = path.relative_to(root).as_posix()
                path.unlink()
                removed.append(hashlib.sha256(relative.encode("utf-8")).hexdigest())
        marker_root = root / ".sb" / "memory-effects"
        for target in request.targets:
            marker = {
                "schema_version": 1,
                "operation": request.operation,
                "target_digest": target.target_digest,
                "request_digest": request.request_digest,
                "tombstone_sequence": request.tombstone_high_water.sequence,
                "tombstone_set_root": request.tombstone_high_water.set_root,
                "effective_at": format_instant(now),
            }
            self._write_private(
                marker_root / f"{target.target_digest[7:]}.json",
                canonical_bytes(marker) + b"\n",
            )
        for prior in prior_records:
            for path in root.rglob("*"):
                if (
                    path.is_file()
                    and ".git" not in path.relative_to(root).parts
                    and prior in path.read_bytes()
                ):
                    raise ErasureError("MANAGED_COPY_REMAINS")
        self.reingress.block_request(request, now)
        return tuple(sorted(removed))


def _scan_regular(root: Path, needles: Sequence[bytes]) -> SurfaceInventoryEntry:
    file_count = 0
    matches = 0
    errors: list[str] = []
    rows: list[dict[str, object]] = []
    object_count = 0
    fd_count = 0
    try:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                errors.append("NON_REGULAR_SURFACE")
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                errors.append("UNREADABLE_SURFACE")
                continue
            count = sum(raw.count(needle) for needle in needles)
            matches += count
            file_count += 1
            rows.append(
                {
                    "surface_id": hashlib.sha256(
                        path.relative_to(root).as_posix().encode("utf-8")
                    ).hexdigest(),
                    "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "matches": count,
                }
            )
        git_root = root if (root / ".git").is_dir() else None
        if git_root is not None:
            listed = subprocess.run(
                ["git", "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"],
                cwd=git_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if listed.returncode != 0:
                errors.append("GIT_OBJECT_SCAN_FAILED")
            else:
                for oid in listed.stdout.splitlines():
                    item = subprocess.run(
                        ["git", "cat-file", "-p", oid],
                        cwd=git_root,
                        check=False,
                        capture_output=True,
                    )
                    if item.returncode != 0:
                        errors.append("GIT_OBJECT_SCAN_FAILED")
                        continue
                    object_count += 1
                    matches += sum(item.stdout.count(needle) for needle in needles)
        proc = Path("/proc") / str(os.getpid()) / "fd"
        if proc.is_dir():
            for descriptor in proc.iterdir():
                try:
                    target = descriptor.resolve()
                except OSError:
                    continue
                if target.is_relative_to(root.resolve()):
                    fd_count += 1
    except OSError:
        errors.append("SURFACE_ENUMERATION_FAILED")
    scan_digest = digest(
        "surface",
        {"files": rows, "objects": object_count, "fds": fd_count, "errors": sorted(errors)},
    )
    return SurfaceInventoryEntry(
        owner="second_brain",
        surface_id=hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
        manifest_digest=digest("surface", {"root": hashlib.sha256(str(root).encode()).hexdigest()}),
        readable=not errors,
        file_count=file_count,
        row_count=0,
        object_count=object_count,
        fd_count=fd_count,
        scan_digest=scan_digest,
        matches=matches,
        errors=tuple(sorted(errors)),
    )


def scan_managed_surfaces(
    roots: Iterable[Path],
    needles: Sequence[bytes],
) -> SurfaceInventory:
    entries = tuple(_scan_regular(root, needles) for root in roots)
    payload = {"entries": [asdict(entry) for entry in entries]}
    return SurfaceInventory(
        entries=entries,
        manifest_digest=digest("surface", payload),
        scan_errors=sum(len(entry.errors) for entry in entries),
        matches=sum(entry.matches for entry in entries),
    )


def purge_matching_managed_copies(roots: Iterable[Path], needles: Sequence[bytes]) -> int:
    removed = 0
    for root in roots:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix(), reverse=True):
            if not path.is_file():
                continue
            raw = path.read_bytes()
            if any(needle in raw for needle in needles):
                path.unlink()
                removed += 1
    return removed


def inventory_json(inventory: SurfaceInventory) -> bytes:
    return canonical_bytes(
        {
            "entries": [asdict(entry) for entry in inventory.entries],
            "manifest_digest": inventory.manifest_digest,
            "scan_errors": inventory.scan_errors,
            "matches": inventory.matches,
        }
    ) + b"\n"
