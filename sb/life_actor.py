"""Authorized Life request identity."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LifeActor:
    source_ids: tuple[str, ...]
    scopes: tuple[str, ...]
    client: bool
    device_id: str = "owner"
    can_write: bool = False
