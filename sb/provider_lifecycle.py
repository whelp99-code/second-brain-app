"""Provider entry-boundary recovery and deterministic export expiry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final

from sb.exports import ExportPublisher


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    disposed_export_digests: tuple[str, ...]
    disposed_staging_keys: tuple[str, ...] = ()


@final
class ProviderLifecycle:
    def __init__(self, exports: ExportPublisher) -> None:
        self.exports = exports

    def maintain(self, now: datetime) -> MaintenanceResult:
        """Recover publication state and enforce logical/physical expiry at `now`."""
        return MaintenanceResult(self.exports.recover(now))
