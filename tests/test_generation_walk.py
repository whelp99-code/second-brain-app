"""Public generation guarantees when pruning private paths and deferring copy sync."""
from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sb import generations
from sb.generations import GenerationError, GenerationStore
from tests.test_generations import NOW, ROOT, build_generation


def test_copy_does_not_walk_excluded_git_or_derived_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for name in (".git/objects/old", ".sb/compiled/old.sha", "wiki/a.md", "raw/aa/blob"):
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        _ = file.write_text(name)
    original = os.scandir
    visited: list[Path] = []

    @contextmanager
    def scan(path: Path | str) -> Generator[Iterator[os.DirEntry[str]], None, None]:
        visited.append(Path(path))
        with original(path) as entries:
            yield entries

    monkeypatch.setattr(os, "scandir", scan)
    GenerationStore._copy_allowed(source, target, lambda _path: True)  # pyright: ignore[reportPrivateUsage]
    assert (target / "wiki/a.md").read_text() == "wiki/a.md"
    assert (target / "raw/aa/blob").read_text() == "raw/aa/blob"
    assert not any(path.is_relative_to(source / ".git") or path.is_relative_to(source / ".sb")
                   for path in visited)


@pytest.mark.parametrize("kind", ["file-symlink", "directory-symlink", "hardlink"])
def test_copy_still_rejects_unsafe_included_entries(tmp_path: Path, kind: str) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    outside = tmp_path / "outside"
    _ = outside.write_text("must not be copied")
    if kind == "hardlink":
        os.link(outside, source / "link")
    else:
        (source / "link").symlink_to(tmp_path if kind == "directory-symlink" else outside)
    with pytest.raises(GenerationError, match="SOURCE_UNSAFE"):
        GenerationStore._copy_allowed(source, target, lambda _path: True)  # pyright: ignore[reportPrivateUsage]


def test_content_inventory_keeps_exact_order_and_exclusions(tmp_path: Path) -> None:
    for name in ("z.md", "a/x.md", "a.md", "raw/.git/value", "nested/generation.json",
                 ".git/objects/ignored", ".sb/index.db", "generation.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(name)
    paths = generations._regular_files(tmp_path, include_derived=False)  # pyright: ignore[reportPrivateUsage]
    assert [relative.as_posix() for _path, relative in paths] == [
        "a.md", "a/x.md", "raw/.git/value", "z.md"]
    paths = generations._regular_files(tmp_path, include_derived=True)  # pyright: ignore[reportPrivateUsage]
    assert [relative.as_posix() for _path, relative in paths] == [
        ".sb/index.db", "a.md", "a/x.md", "raw/.git/value", "z.md"]


def test_final_file_sync_failure_keeps_predecessor_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = GenerationStore(tmp_path / "state", tmp_path / "share",
                            provider_instance_id="provider:test", provider_release_sha="a" * 40)
    try:
        first = build_generation(store, text="preserved original")
        store.activate(first, None, NOW)
        original = os.fsync
        phases: list[str] = []

        def sync(fd: int) -> None:
            target = Path(os.readlink(f"/proc/self/fd/{fd}"))
            if target.name == "value.md" and ".staging" in target.parts:
                assert "brief_build" in phases, "copy flushed before the final durability boundary"
                raise OSError("fixture final file sync failed")
            original(fd)

        monkeypatch.setattr(os, "fsync", sync)
        with pytest.raises(OSError, match="fixture final file sync failed"):
            _ = store.build(request_id="deferred-sync", parent=first, tombstone_sequence=0,
                            tombstone_set_root=ROOT, created_at=NOW, allowed=lambda _path: True,
                            mutate=lambda _root: None, barrier=phases.append)
        assert store.active().generation_id == first.generation_id
        assert (first.root / "wiki/value.md").read_text() == "preserved original"
        assert not tuple(store.staging.iterdir())
    finally:
        store.close()
