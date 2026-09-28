"""Optional source adapter contract for bounded raw Life exports."""

from typing import Protocol, runtime_checkable

from sb.connectors.base import SourceAdapter


@runtime_checkable
class LifeExportAdapter(SourceAdapter, Protocol):
    supports_life_events: bool
    life_format: str
    life_timezone: str
