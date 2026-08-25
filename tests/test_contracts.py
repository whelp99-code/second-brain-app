"""Tests for sb.contracts frozen dataclasses."""

import pytest

from sb.contracts import (
    Blob,
    BriefingInputs,
    ConflictVerdict,
    PageSpec,
    SourceCite,
    SourceRef,
    Unit,
)


def test_conflict_verdict_valid_relations_construct() -> None:
    for relation in ("supports", "contradicts", "unrelated", "supersedes"):
        verdict = ConflictVerdict(relation=relation, confidence=0.9, rationale="because")
        assert verdict.relation == relation


def test_conflict_verdict_invalid_relation_raises_value_error() -> None:
    with pytest.raises(ValueError):
        ConflictVerdict(relation="bogus", confidence=0.5, rationale="x")


def test_conflict_verdict_is_frozen() -> None:
    verdict = ConflictVerdict(relation="supports", confidence=0.9, rationale="because")
    with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
        verdict.relation = "contradicts"  # type: ignore[misc]


def test_source_ref_roundtrip() -> None:
    ref = SourceRef(source_id="me-wiki", source_uri="identity/profile.md", source_version="abc123")
    assert ref.source_id == "me-wiki"
    assert ref.source_uri == "identity/profile.md"
    assert ref.source_version == "abc123"


def test_blob_fields() -> None:
    blob = Blob(hash="deadbeef", size=42)
    assert blob.hash == "deadbeef"
    assert blob.size == 42


def test_unit_fields() -> None:
    unit = Unit(
        unit_id="u1",
        content_hash="c1",
        span="0-10",
        text="hello world",
        origin="me-wiki:identity/profile.md",
    )
    assert unit.unit_id == "u1"
    assert unit.text == "hello world"


def test_source_cite_default_spans_empty() -> None:
    cite = SourceCite(sid="deadbeef", origin="me-wiki:identity/profile.md", hash="deadbeef" * 8)
    assert cite.spans == []


def test_page_spec_holds_sources() -> None:
    cite = SourceCite(sid="deadbeef", origin="me-wiki:identity/profile.md", hash="deadbeef" * 8)
    page = PageSpec(
        page_id="me-wiki-identity-profile",
        title="Profile",
        body_md="Some body.[^deadbeef]",
        sources=[cite],
        status="active",
    )
    assert page.sources == [cite]
    assert page.status == "active"


def test_briefing_inputs_tuple_fields() -> None:
    inputs = BriefingInputs(
        yesterday_items=("a", "b"),
        open_conflict_pages=(),
        stale_pages=("stale-page",),
        upcoming_items=(),
        last_brief=None,
        previous_run_status=None,
    )
    assert inputs.yesterday_items == ("a", "b")
    assert inputs.open_conflict_pages == ()
    assert inputs.last_brief is None
    assert inputs.previous_run_status is None
