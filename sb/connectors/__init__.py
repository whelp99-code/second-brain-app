"""Connector package: one auto-discovery registry for SourceAdapter modules."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType, ModuleType
from typing import Protocol, override, runtime_checkable

from sb.config import Config
from sb.connectors.base import ItemMeta, SourceAdapter

_DISCOVERABLE_EXACT: frozenset[str] = frozenset({"unified_db", "markdown_vault"})


@runtime_checkable
class AdapterModule(Protocol):
    """Discoverable connector module: unique id plus a typed factory."""

    ADAPTER_ID: str
    create: Callable[[Config], SourceAdapter]


@dataclass(frozen=True, slots=True)
class DuplicateAdapterId(Exception):
    adapter_id: str

    @override
    def __str__(self) -> str:
        return f"duplicate adapter id: {self.adapter_id}"


def _is_discoverable(name: str) -> bool:
    return (
        name.startswith(("sessions_", "records_"))
        or name.endswith("_documents")
        or name in _DISCOVERABLE_EXACT
    )


def discover_adapters(
    config: Config, *, package: ModuleType | None = None
) -> Mapping[str, SourceAdapter]:
    """Load discoverable connector modules and instantiate each once.

    A discoverable module is named `sessions_*`, `records_*`, `*_documents`,
    `unified_db`, or `markdown_vault`, and MUST export `ADAPTER_ID: str` plus
    `create(config) -> SourceAdapter`. Duplicate ids raise DuplicateAdapterId.
    Later connector todos add conforming modules and never edit this registry.
    """
    pkg = package if package is not None else sys.modules[__name__]
    found: dict[str, SourceAdapter] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if not _is_discoverable(info.name):
            continue
        loaded = importlib.import_module(f"{pkg.__name__}.{info.name}")
        if not isinstance(loaded, AdapterModule):
            raise DuplicateAdapterId(info.name)
        adapter_id = loaded.ADAPTER_ID
        if not adapter_id:
            raise DuplicateAdapterId(adapter_id)
        if adapter_id in found:
            raise DuplicateAdapterId(adapter_id)
        found[adapter_id] = loaded.create(config)
    return MappingProxyType(found)


__all__ = [
    "DuplicateAdapterId",
    "ItemMeta",
    "SourceAdapter",
    "discover_adapters",
]
