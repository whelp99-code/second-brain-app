"""Core5 B04 Korean locator and B05 access-boundary regressions."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.memory_records import parse_page_records
from sb.page_access import PageAccess
from sb.restore_access import RestorePageAccess
from sb.scoped_surfaces import ScopedSurfaceRejected, require_restore_scope
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1
from sb.vault import init_vault
from tests.knowledge import commit_page, stamp_knowledge

pytest_plugins = ("tests.test_memory_access",)


def test_b04_korean_search_hit_resolves_to_utf8_citation_locator(tmp_path: Path) -> None:
    """Given Korean committed text, search and citation spans identify the same bytes."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/compass.md",
        "# 절차\n은빛 나침반 절차.[^deadbeef]\n\n[^deadbeef]: me-wiki:notes/compass.md\n",
    )
    stamp_knowledge(root)

    from sb.search import SearchIndex

    hits = SearchIndex(root).search("은빛나침반")
    hit = next(item for item in hits if item.page_id == "wiki/compass")
    raw = (root / "wiki" / "compass.md").read_bytes()
    records = parse_page_records(raw, hit.page_id)

    assert hit.section == "절차"
    assert "은빛 나침반" in hit.snippet
    assert len(records) == 1
    record = records[0]
    assert raw[record.citation_span_start:record.citation_span_end] == record.record_text.encode()
    assert record.citation_span_start < record.citation_span_end
    assert record.citation_identity_full


def test_b05_corrected_page_denies_personal_scope_to_project_reader(
    classified: tuple[Path, str, GenerationIdentityV1],
) -> None:
    """Given a classified personal page, a project-only reader cannot access it."""
    root, name, generation = classified
    page = replace(
        classified_page(root, name, generation),
        requirements=(SourceAccess("principal:owner", (), "1"),),
    )

    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_scope(page, SourceAccess("principal:owner", ("project:a",), "1"))


def test_b05_restored_page_denies_scope_not_in_current_policy() -> None:
    """Given restored source requirements, restore projection remains fail-closed."""
    page = RestorePageAccess(
        page_id="wiki/restored",
        content_digest="sha256:" + "a" * 64,
        requirements=PageAccess(("sha256:" + "b" * 64,), True),
        sources=((
            "sha256:" + "b" * 64,
            SourceAccess("principal:owner", ("project:private",), "policy:2"),
        ),),
    )

    with pytest.raises(ScopedSurfaceRejected, match="MEMORY_SCOPED_RESTORE_DENIED"):
        require_restore_scope((page,), SourceAccess("principal:owner", ("project:public",), "policy:2"))
