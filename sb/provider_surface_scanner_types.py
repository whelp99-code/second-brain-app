"""Typed roots consumed by the fixed provider surface scanner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProviderSurfaceLayout:
    generation_root: Path
    request_root: Path
    state_root: Path
    share_root: Path
    export_root: Path
    backup_root: Path
    staging_root: Path
    retired_root: Path
