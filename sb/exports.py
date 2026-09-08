"""Fixed-root record-level export publication, expiry, and invalidation."""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path
from typing import final

from sb.export_journal import ExportJournal
from sb.export_models import (
    EXPORT_RETENTION_MS,
    ExportError,
    ExportFileV1,
    MemoryExportManifestV1,
)
from sb.export_publication import ExportPublication, ExportPublicationService
from sb.export_retention import ExportRetentionService

__all__ = (
    "EXPORT_RETENTION_MS",
    "ExportError",
    "ExportFileV1",
    "ExportPublication",
    "ExportPublisher",
    "MemoryExportManifestV1",
)


@final
class ExportPublisher:
    def __init__(
        self,
        root: Path,
        provider_release_sha: str,
        journal: ExportJournal,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = root.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink < 2
        ):
            raise ExportError("EXPORT_ROOT_UNSAFE")
        root.chmod(0o700)
        self._root = root
        self._publication = ExportPublicationService(root, provider_release_sha, journal)
        self._retention = ExportRetentionService(root, journal)

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, publication: ExportPublication) -> MemoryExportManifestV1:
        return self._publication.publish(publication)

    def read_manifest(self, request_id: str, now: datetime) -> MemoryExportManifestV1:
        return self._retention.read_manifest(request_id, now)

    def validate(self, now: datetime) -> None:
        self._retention.validate(now)

    def recover(self, now: datetime) -> tuple[str, ...]:
        return self._retention.recover(now)

    def expire(self, now: datetime) -> tuple[str, ...]:
        return self._retention.expire(now)

    def invalidate(self, identities: set[str], now: datetime) -> tuple[str, ...]:
        return self._retention.invalidate(identities, now)
