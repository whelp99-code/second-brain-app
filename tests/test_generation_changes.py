"""Sealed recent-change history survives disposal without inventing Git dates."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generation_changes import GenerationChangesError, generation_recent_changes
from sb.generation_integrity import GenerationIntegrityError
from sb.generations import Generation, GenerationStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[GenerationStore]:
    with closing(GenerationStore(tmp_path / "state", tmp_path / "share",
            provider_instance_id="provider:fixture", provider_release_sha="a" * 40)) as value:
        yield value


def publish(store: GenerationStore, parent: Generation | None, pages: Mapping[str, str]) -> Generation:
    now = datetime.now(UTC)
    def mutate(root: Path) -> None:
        wiki = root / "wiki"
        wiki.mkdir(exist_ok=True)
        for page in wiki.glob("*.md"):
            page.unlink()
        for name, text in pages.items():
            _ = (wiki / f"{name}.md").write_text(text)
    generation = store.build(request_id=str(now), parent=parent, tombstone_sequence=0,
        tombstone_set_root="sha256:" + "0" * 64, created_at=now,
        allowed=lambda _relative: True, mutate=mutate)
    store.activate(generation, parent, now)
    return generation


def test_deltas_distinguish_added_modified_deleted_and_unchanged(store: GenerationStore) -> None:
    # Given: two independent sealed root commits and a disposed parent.
    parent = publish(store, None, {"stable": "unchanged", "changed": "before", "removed": "before"})
    current = publish(store, parent, {"stable": "unchanged", "changed": "after", "added": "after"})
    today = current.manifest.created_at[:10]
    assert not parent.root.exists()
    # When: recent changes are read from activation metadata, not the fixed Git timestamp.
    rows = generation_recent_changes(current.root, store.journal_path, 7)
    # Then: only actual deltas appear for the latest generation, with real activation dates.
    assert [(row.page_id, row.change, row.date) for row in rows[:3]] == [
        ("wiki/added", "added", today), ("wiki/changed", "modified", today),
        ("wiki/removed", "deleted", today)]
    assert [(row.page_id, row.change) for row in rows[3:]] == [
        ("wiki/changed", "added"), ("wiki/removed", "added"), ("wiki/stable", "added")]


def test_missing_change_receipt_cannot_report_an_empty_success(store: GenerationStore) -> None:
    # Given: an older/restored generation whose predecessor receipt is unavailable.
    parent = publish(store, None, {"first": "one"})
    current = publish(store, parent, {"second": "two"})
    _ = store.journal.execute("DELETE FROM generation_changes WHERE generation_id=?", (parent.generation_id,))
    # When / Then: no empty or partial-success fallback conceals the missing history.
    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_UNAVAILABLE"):
        _ = generation_recent_changes(current.root, store.journal_path, 7)


def test_missing_parent_manifest_cannot_classify_existing_pages_as_added(store: GenerationStore) -> None:
    # Given: the named parent is corrupt rather than a genuine genesis generation.
    parent = publish(store, None, {"first": "one"})
    parent.root.chmod(0o700)
    (parent.root / "generation.json").unlink()
    # When / Then: delta capture fails instead of treating the parent as empty.
    with pytest.raises(GenerationIntegrityError):
        _ = store.build(request_id="corrupt-parent", parent=parent, tombstone_sequence=0,
            tombstone_set_root="sha256:" + "0" * 64, created_at=datetime.now(UTC),
            allowed=lambda _relative: True, mutate=lambda _root: None)


def test_stale_journal_binding_cannot_mix_generation_changes(store: GenerationStore) -> None:
    # Given: the active manifest and the journal disagree about the committed head.
    current = publish(store, None, {"first": "one"})
    _ = store.journal.execute("UPDATE generation_changes SET head=? WHERE generation_id=?",
                             ("f" * 40, current.generation_id))
    # When / Then: the read rejects split generation identity.
    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_STALE"):
        _ = generation_recent_changes(current.root, store.journal_path, 7)


def test_vault_above_census_budget_records_only_real_changes(store: GenerationStore) -> None:
    # Given: a schema-5-style first seal of an existing vault larger than the
    # receipt census, then one real edit. Unchanged pages are the baseline.
    pages = {f"p{index:04d}": "same" for index in range(4097)}
    parent = publish(store, None, pages)
    pages["p0000"] = "edited"
    current = publish(store, parent, pages)
    # When: recent changes are read after both seals.
    rows = generation_recent_changes(current.root, store.journal_path, 7)
    # Then: refresh-sized change set is the edit, not the 4097 existing pages.
    assert [(row.page_id, row.change) for row in rows] == [("wiki/p0000", "modified")]


def test_unactivated_generation_has_no_recent_publication(store: GenerationStore) -> None:
    # Given: a sealed candidate has not crossed the activation boundary.
    current = store.build(request_id="sealed-only", parent=None, tombstone_sequence=0,
        tombstone_set_root="sha256:" + "0" * 64, created_at=datetime.now(UTC),
        allowed=lambda _relative: True, mutate=lambda _root: None)
    # When / Then: the journal cannot invent an activation time from created_at.
    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_UNAVAILABLE"):
        _ = generation_recent_changes(current.root, store.journal_path, 7)
