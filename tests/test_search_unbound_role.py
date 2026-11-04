"""Drop an unbound role word only when the full AND misses."""

from __future__ import annotations

from pathlib import Path

from sb.search import SearchIndex, without_unbound_role
from sb.vault import init_vault
from tests.knowledge import commit_page, stamp_knowledge

EXPECTED = "wiki/expected-quote"
OTHER = "wiki/other-quote"


def _vault(tmp_path: Path) -> Path:
    root = init_vault(tmp_path / "vault").root
    commit_page(root, EXPECTED + ".md", "# 견적\n보안통합 견적 전달\n")
    commit_page(root, OTHER + ".md", "# 견적\n고객사 견적 전달\n")
    stamp_knowledge(root)
    return root


def test_role_word_is_not_rewritten_to_a_company_name() -> None:
    assert without_unbound_role("고객사 보안통합 견적") == "보안통합 견적"
    assert without_unbound_role("고객사") is None
    assert without_unbound_role("보안통합 견적") is None


def test_missed_and_drops_role_word_and_keeps_the_specific_card(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    hits = SearchIndex(vault_root=root).search("고객사 보안통합 견적")
    assert [hit.page_id for hit in hits] == [EXPECTED]


def test_matching_role_query_is_not_relaxed(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    hits = SearchIndex(vault_root=root).search("고객사 견적")
    assert [hit.page_id for hit in hits] == [OTHER]


def test_unrelated_miss_stays_empty(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    assert SearchIndex(vault_root=root).search("없는고유어 보안통합") == ()
