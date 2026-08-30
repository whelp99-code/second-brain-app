"""Durable knowledge-state registry: authority, projection, compile flags."""

from __future__ import annotations

from pathlib import Path

from sb.compile import compile_pages, compile_state_report
from sb.config import Config, default_knowledge_registry_path
from sb.knowledge_registry import UNKNOWN, KnowledgeRegistry, missing_state
from sb.search import SearchIndex
from sb.vault import init_vault
from tests.knowledge import commit_page, register_page, registry_file


def _cfg(root: Path, registry: Path) -> Config:
    return Config(
        raw={"vault_root": str(root), "knowledge_registry": str(registry)},
        base_dir=root,
    )


def test_missing_page_id_is_unknown(tmp_path: Path) -> None:
    """Given no registry row, when get is called, then status is UNKNOWN."""
    registry = KnowledgeRegistry(tmp_path / "knowledge-registry.sqlite")
    state = registry.get("wiki/never-registered")
    assert state == missing_state("wiki/never-registered")
    assert state.knowledge_status == UNKNOWN
    assert state.approval_status == UNKNOWN
    assert state.revision == 0


def test_yaml_knowledge_status_is_not_authority(tmp_path: Path) -> None:
    """Given YAML ACTIVE+APPROVED and no registry row, when searching, then the page is excluded."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/yaml-only.md",
        "---\ntitle: YamlOnly\nknowledge_status: ACTIVE\napproval_status: APPROVED\n---\n"
        "\n# YamlOnly\nYamlAuthorityToken must not leak.\n",
    )
    index = SearchIndex(vault_root=root, registry_path=registry_file(root))
    assert index.search("YamlAuthorityToken") == ()
    assert index.search("YamlAuthorityToken", scope="candidate") == ()


def test_registry_projects_into_search_unindexed_columns(tmp_path: Path) -> None:
    """Given a registry ACTIVE+APPROVED row, when default-searching, then fields match."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/approved.md",
        "---\ntitle: ApprovedPage\nsource_ref: inbox:approved.md\nupdated: '2026-08-29'\n---\n"
        "\n# ApprovedPage\nApprovedKnowledgeToken is confirmed.\n",
    )
    register_page(
        root,
        "wiki/approved",
        knowledge_status="ACTIVE",
        approval_status="APPROVED",
        canonical="wiki/approved",
    )
    index = SearchIndex(vault_root=root, registry_path=registry_file(root))
    hits = index.search("ApprovedKnowledgeToken")
    assert hits
    hit = hits[0]
    assert hit.page_id == "wiki/approved"
    assert hit.knowledge_status == "ACTIVE"
    assert hit.approval_status == "APPROVED"
    assert hit.canonical == "wiki/approved"
    assert hit.source_ref == "inbox:approved.md"
    assert hit.kind == "wiki"


def test_compile_state_report_does_not_write_vault_or_create_status(tmp_path: Path) -> None:
    """Given --dry-run/--state-report, when compile reports, then vault and registry stay put."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/bare.md",
        "---\ntitle: Bare\n---\n\n# Bare\nCompileFlagToken.\n",
    )
    wiki = (root / "wiki" / "bare.md").read_bytes()
    registry_path = tmp_path / "knowledge-registry.sqlite"
    before = list(root.rglob("*.md"))
    config = _cfg(root, registry_path)
    dry = compile_state_report(config, dry_run=True, project=False)
    report = compile_state_report(config, dry_run=False, project=True)
    assert dry["vault_written"] is False
    assert dry["status_created"] is False
    assert dry["projected"] is False
    assert report["vault_written"] is False
    assert report["status_created"] is False
    assert report["projected"] is True
    assert report["pages"] == []
    assert (root / "wiki" / "bare.md").read_bytes() == wiki
    assert list(root.rglob("*.md")) == before
    assert KnowledgeRegistry(registry_path).all_states() == ()


def test_compile_pages_symbol_does_not_touch_registry() -> None:
    """Given the cited compiler, when inspecting it, then it has no registry writes."""
    import inspect

    source = inspect.getsource(compile_pages)
    assert "KnowledgeRegistry" not in source
    assert "knowledge_status" not in source
    assert default_knowledge_registry_path().name == "knowledge-registry.sqlite"
