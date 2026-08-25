"""Connector registry: unique ADAPTER_ID discovery and duplicate rejection."""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from sb.config import load_config
from sb.connectors import DuplicateAdapterId, discover_adapters

_FAKE_ADAPTER = textwrap.dedent(
    """\
    from collections.abc import Iterator

    from sb.config import Config
    from sb.connectors.base import ItemMeta, SourceAdapter
    from sb.contracts import SourceRef

    ADAPTER_ID = "{adapter_id}"


    class _Fake:
        source_id = ADAPTER_ID

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
            yield from ()

        def next_cursor(self) -> str:
            return ""


    def create(config: Config) -> SourceAdapter:
        del config
        return _Fake()
    """
)


def _install_package(tmp_path: Path, package_name: str, modules: dict[str, str]) -> ModuleType:
    pkg = tmp_path / package_name
    pkg.mkdir()
    _ = (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name, body in modules.items():
        _ = (pkg / f"{name}.py").write_text(body, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    _ = sys.modules.pop(package_name, None)
    for name in modules:
        _ = sys.modules.pop(f"{package_name}.{name}", None)
    return importlib.import_module(package_name)


def test_registry_auto_discovers_markdown_vault_adapter() -> None:
    # Given: the real sb.connectors package with markdown_vault present.
    config = load_config()

    # When: adapters are discovered from the package.
    registry = discover_adapters(config)

    # Then: markdown-vault is present exactly once.
    assert "markdown-vault" in registry
    assert registry["markdown-vault"].source_id == "me-wiki"


def test_registry_auto_discovers_fixture_module(tmp_path: Path) -> None:
    # Given: a throwaway package with one discoverable sessions_* module.
    pkg = _install_package(
        tmp_path,
        "fix_connectors",
        {"sessions_fixture": _FAKE_ADAPTER.format(adapter_id="sessions-fixture")},
    )

    # When: the registry scans that package.
    registry = discover_adapters(load_config(), package=pkg)

    # Then: the fixture module is registered under its ADAPTER_ID.
    assert list(registry) == ["sessions-fixture"]
    assert registry["sessions-fixture"].source_id == "sessions-fixture"


def test_registry_rejects_duplicate_adapter_id(tmp_path: Path) -> None:
    # Given: two discoverable modules exporting the same ADAPTER_ID.
    body = _FAKE_ADAPTER.format(adapter_id="dup")
    pkg = _install_package(
        tmp_path,
        "dup_connectors",
        {"sessions_one": body, "records_two": body},
    )

    # When / Then: discovery refuses the colliding id.
    with pytest.raises(DuplicateAdapterId, match="dup"):
        _ = discover_adapters(load_config(), package=pkg)


def test_registry_ignores_non_discoverable_module_names(tmp_path: Path) -> None:
    # Given: a helper module whose name is not in the discoverable set.
    pkg = _install_package(
        tmp_path,
        "skip_connectors",
        {
            "fs_safety": _FAKE_ADAPTER.format(adapter_id="should-not-load"),
            "markdown_vault": _FAKE_ADAPTER.format(adapter_id="markdown-vault"),
        },
    )

    # When: the registry scans that package.
    registry = discover_adapters(load_config(), package=pkg)

    # Then: only the discoverable module is loaded.
    assert list(registry) == ["markdown-vault"]
