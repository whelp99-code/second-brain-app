from pathlib import Path

import pytest

from sb.pipeline import audit_citations
from sb.remember_page import materialize_remember
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault, read_page_spec


def test_same_request_is_idempotent_and_distinct_origins_are_preserved(tmp_path: Path) -> None:
    for candidate in ("candidate-a", "candidate-a", "candidate-b"):
        materialize_remember(tmp_path, content="공통 결정", candidate_id=candidate,
                             created_at="2026-09-07T00:00:00Z", release_sha="a" * 40)
    pages = tuple((tmp_path / "wiki").glob("*.md"))
    assert len(pages) == 2
    assert len(tuple((tmp_path / "raw").glob("*/*"))) == 1
    assert audit_citations(tmp_path) == ()
    assert any("memory-candidate:candidate-a" in page.read_text() for page in pages)
    assert any("memory-candidate:candidate-b" in page.read_text() for page in pages)


def test_multiline_input_and_literal_footnotes_have_only_cas_backed_citations(tmp_path: Path) -> None:
    content = "첫 결정\n\n두 번째 결정 [^unknown]"
    materialize_remember(tmp_path, content=content, candidate_id="candidate-a",
                         created_at="2026-09-07T00:00:00Z", release_sha="a" * 40)
    assert next((tmp_path / "raw").glob("*/*")).read_text() == content
    assert audit_citations(tmp_path) == ()


def test_erasure_rebinding_does_not_launder_preexisting_missing_sources(tmp_path: Path) -> None:
    materialize_remember(tmp_path, content="기존 기록", candidate_id="candidate-a",
                         created_at="2026-09-07T00:00:00Z", release_sha="a" * 40)
    page = next((tmp_path / "wiki").glob("*.md"))
    original = page.read_bytes()
    next((tmp_path / "raw").glob("*/*")).unlink()
    Vault(tmp_path).rebind_erased_sources(
        "unrelated-effect", frozenset({"a" * 64}), ContentAddressedStore(tmp_path).put,
    )
    assert page.read_bytes() == original
    assert audit_citations(tmp_path)


@pytest.mark.parametrize("content", ["\u2028".join(["a"] * 65), "[^x]" * 800])
def test_unreadable_record_sets_are_rejected_before_cas_write(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match="WRITE_REQUEST_INVALID"):
        materialize_remember(tmp_path, content=content, candidate_id="candidate-a",
                             created_at="2026-09-07T00:00:00Z", release_sha="a" * 40)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("sensitivity", ["public", "personal", "sensitive", "restricted"])
def test_request_sensitivity_survives_page_roundtrip(tmp_path: Path, sensitivity: str) -> None:
    materialize_remember(tmp_path, content="기억 분류", candidate_id="candidate-a",
                         created_at="2026-09-07T00:00:00Z", release_sha="a" * 40,
                         sensitivity=sensitivity)
    path = next((tmp_path / "wiki").glob("*.md"))
    page = read_page_spec(tmp_path, "wiki/" + path.stem)
    assert page is not None and page.sensitivity == sensitivity
