"""Crash-safe export validation, logical cutoff, expiry, and invalidation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Literal, final

from sb.effect_values import digest, parse_instant
from sb.export_files import directory_fsync, read_manifest
from sb.export_journal import ExportJournal
from sb.export_models import ExportError, MemoryExportManifestV1


@final
class ExportRetentionService:
    def __init__(self, root: Path, journal: ExportJournal) -> None:
        self.root = root
        self.journal = journal

    def read_manifest(self, request_id: str, now: datetime) -> MemoryExportManifestV1:
        _ = self.recover(now)
        record = self.journal.get(request_id)
        if record is None or record.state != "available" or parse_instant(record.expires_at) <= now:
            raise ExportError("EXPORT_EXPIRED")
        return read_manifest(self.root, request_id)

    def validate(self, now: datetime) -> None:
        _ = self.recover(now)
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            metadata = path.stat(follow_symlinks=False)
            if (
                path.name.startswith(".")
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")
            names = {item.name for item in path.iterdir()}
            if names != {"memory.json", "manifest.json"}:
                raise ExportError("EXPORT_ROOT_UNSAFE")
            manifest = read_manifest(self.root, path.name)
            record = self.journal.get(path.name)
            if (
                record is None
                or record.state != "available"
                or manifest.request_id != path.name
                or parse_instant(manifest.expires_at) <= now
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")
            data = path / "memory.json"
            metadata_rows = (
                data.stat(follow_symlinks=False),
                (path / "manifest.json").stat(follow_symlinks=False),
            )
            if any(
                not stat.S_ISREG(item.st_mode)
                or item.st_uid != os.getuid()
                or item.st_nlink != 1
                or stat.S_IMODE(item.st_mode) != 0o600
                for item in metadata_rows
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")
            raw = data.read_bytes()
            expected = manifest.files[0]
            if (
                expected.name != "memory.json"
                or expected.bytes != len(raw)
                or expected.digest != "sha256:" + hashlib.sha256(raw).hexdigest()
            ):
                raise ExportError("EXPORT_ROOT_UNSAFE")

    def _dispose(
        self,
        request_id: str,
        disposition: Literal["expired", "invalidated"],
        now: datetime,
    ) -> str:
        record = self.journal.disposing(request_id, disposition, now)
        identity = hashlib.sha256(request_id.encode()).hexdigest()
        residue = self.root / f".{disposition}-{identity}.{record.disposal_fence}"
        final = self.root / request_id
        staging = tuple(self.root.glob(f".staging-{request_id}.*"))
        if len(staging) > 1:
            raise ExportError("EXPORT_ROOT_UNSAFE")
        source = final if final.is_dir() and not final.is_symlink() else (staging[0] if staging else None)
        if source is not None and source != residue:
            if residue.exists() or residue.is_symlink():
                raise ExportError("EXPORT_ROOT_UNSAFE")
            os.replace(source, residue)
            directory_fsync(self.root)
        if residue.exists():
            shutil.rmtree(residue)
            directory_fsync(self.root)
        disposal_digest = digest(
            "export",
            {
                "request_id": request_id,
                "disposition": disposition,
                "fence": record.disposal_fence,
                "disposed": True,
            },
        )
        _ = self.journal.disposed(request_id, disposal_digest, now)
        return identity

    def recover(self, now: datetime) -> tuple[str, ...]:
        removed: list[str] = []
        for record in self.journal.all():
            final = self.root / record.request_id
            staging = tuple(self.root.glob(f".staging-{record.request_id}.*"))
            if record.state == "publishing":
                if final.is_dir() and not final.is_symlink():
                    _ = self.journal.available(record.request_id, now)
                elif len(staging) == 1:
                    os.replace(staging[0], final)
                    directory_fsync(self.root)
                    _ = self.journal.available(record.request_id, now)
                else:
                    removed.append(self._dispose(record.request_id, "invalidated", now))
            current = self.journal.get(record.request_id)
            if current is None:
                raise ExportError("EXPORT_JOURNAL_CORRUPT")
            if current.state == "available" and parse_instant(current.expires_at) <= now:
                removed.append(self._dispose(current.request_id, "expired", now))
            elif current.state == "disposing" and current.disposition is not None:
                removed.append(self._dispose(current.request_id, current.disposition, now))
            elif current.state in {"expired", "invalidated"}:
                identity = hashlib.sha256(current.request_id.encode()).hexdigest()
                residues = (
                    final,
                    *self.root.glob(f".expired-{identity}.*"),
                    *self.root.glob(f".invalidated-{identity}.*"),
                    *staging,
                )
                for residue in residues:
                    if residue.exists() and not residue.is_symlink():
                        shutil.rmtree(residue)
                        directory_fsync(self.root)
        self._reject_unknown_entries()
        return tuple(sorted(set(removed)))

    def _reject_unknown_entries(self) -> None:
        records = self.journal.all()
        known = {record.request_id for record in records}
        for record in records:
            known.update(path.name for path in self.root.glob(f".staging-{record.request_id}.*"))
            identity = hashlib.sha256(record.request_id.encode()).hexdigest()
            known.update(path.name for path in self.root.glob(f".expired-{identity}.*"))
            known.update(path.name for path in self.root.glob(f".invalidated-{identity}.*"))
        if any(path.name not in known for path in self.root.iterdir()):
            raise ExportError("EXPORT_ROOT_UNSAFE")

    def expire(self, now: datetime) -> tuple[str, ...]:
        return self.recover(now)

    def invalidate(self, identities: set[str], now: datetime) -> tuple[str, ...]:
        _ = self.recover(now)
        removed: list[str] = []
        for record in self.journal.all():
            if record.state != "available":
                continue
            manifest = read_manifest(self.root, record.request_id)
            managed_identities = {
                *manifest.target_ids,
                *manifest.source_identities,
                *manifest.content_identities,
                *manifest.citation_identities,
            }
            if identities.intersection(managed_identities):
                removed.append(self._dispose(record.request_id, "invalidated", now))
        return tuple(removed)
