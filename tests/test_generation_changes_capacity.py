"""Capacity and malformed-tree fences for sealed generation change receipts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sb import generation_changes
from sb.generation_changes import GenerationChangesError


class SyntheticGeneration:
    root = Path("/synthetic/repository")
    generation_id = "synthetic-generation"
    head = "a" * 40


def tree_with_pages(count: int) -> bytes:
    return b"".join(
        b"100644 blob "
        + f"{index:040x}".encode("ascii")
        + b"\t"
        + f"wiki/page-{index:05d}.md".encode("ascii")
        + b"\0"
        for index in range(count)
    )


def pages_from(monkeypatch: pytest.MonkeyPatch, tree: bytes) -> dict[str, str]:
    monkeypatch.setattr(
        generation_changes.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=tree),
    )
    return dict(generation_changes._pages(SyntheticGeneration()))


def test_pages_above_the_legacy_capacity_are_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = pages_from(monkeypatch, tree_with_pages(8_684 + 340))

    assert len(pages) == 8_684 + 340
    assert pages["wiki/page-09023"] == f"{9023:040x}"


def test_page_count_above_the_current_capacity_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_BUDGET"):
        _ = pages_from(monkeypatch, tree_with_pages(generation_changes._MAX_PAGES + 1))


def test_invalid_tree_metadata_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = b"100644 blob " + b"a" * 40 + b" wiki/missing-tab.md\0"

    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_INVALID"):
        _ = pages_from(monkeypatch, malformed)


def test_tree_byte_budget_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized = b"x" * (generation_changes._MAX_TREE_BYTES + 1)

    with pytest.raises(GenerationChangesError, match="GENERATION_CHANGES_UNAVAILABLE"):
        _ = pages_from(monkeypatch, oversized)
