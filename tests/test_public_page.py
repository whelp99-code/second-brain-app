from sb.public_page import public_frontmatter


def test_empty_source_list_after_erasure_uses_public_scalar() -> None:
    assert public_frontmatter({"sources": "[]"}, "wiki/alpha") == {"sources": ""}
    for stored in ("", "[unexpected]", "invalid"):
        assert public_frontmatter({"sources": stored}, "wiki/alpha") == {"sources": stored}
    assert "sources" not in public_frontmatter({}, "wiki/alpha")


def test_logical_and_qualified_ids_bind_to_the_same_committed_path() -> None:
    assert public_frontmatter({"id": "alpha"}, "wiki/alpha") == {"id": "wiki/alpha"}
    assert public_frontmatter({"id": "wiki/alpha"}, "alpha") == {"id": "alpha"}


def test_projection_never_conceals_mismatched_or_invalid_page_identity() -> None:
    for stored in ("beta", "daily/alpha", "../alpha", ""):
        assert public_frontmatter({"id": stored}, "wiki/alpha") == {"id": stored}
    assert public_frontmatter({}, "wiki/alpha") == {}
