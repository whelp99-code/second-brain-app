"""Markdown vault adapter: scan, cursor resume, skips, nested .git exclusion."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from sb.connectors.base import ItemMeta
from sb.connectors.markdown_vault import (
    MarkdownVaultAdapter,
    MarkdownVaultError,
    decode_source_cursor,
    encode_source_cursor,
)
from sb.contracts import SourceRef

_CURSOR_TOKEN: re.Pattern[str] = re.compile(r"^\d+:\d+:[0-9a-f]{64}$")


def _write_md(root: Path, relative: str, body: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(body, encoding="utf-8")
    return path


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[tuple[str, bytes]]:
    return [(ref.source_uri, body) for ref, body, meta in items if "skip_reason" not in meta]


def test_scan_yields_source_ref_bytes_meta_per_markdown_file(tmp_path: Path) -> None:
    # Given: a fixture markdown tree with nested and root-level pages.
    root = tmp_path / "vault"
    first = _write_md(root, "a.md", "# A\n")
    second = _write_md(root, "nested/b.md", "# B\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: each .md is delivered as SourceRef + raw bytes + cursor meta.
    delivered = _delivered(items)
    assert delivered == [
        ("a.md", first.read_bytes()),
        ("nested/b.md", second.read_bytes()),
    ]
    for ref, body, meta in items:
        token = meta.get("cursor")
        relative = meta.get("relative_path")
        assert ref.source_id == "fixture"
        assert isinstance(ref, SourceRef)
        assert isinstance(body, bytes)
        assert token is not None
        assert _CURSOR_TOKEN.fullmatch(token)
        assert ref.source_version == token
        assert relative == ref.source_uri


def test_unchanged_rescan_with_returned_cursor_yields_zero_items(tmp_path: Path) -> None:
    # Given: a scanned markdown tree whose cursor has been captured.
    root = tmp_path / "vault"
    _ = _write_md(root, "kept.md", "hello\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")
    first = list(adapter.scan(None))
    assert _delivered(first)
    cursor = adapter.next_cursor()

    # When: the same adapter rescans with the returned cursor and no file changes.
    second = list(adapter.scan(cursor))

    # Then: zero items are delivered.
    assert second == []
    assert adapter.next_cursor() == cursor


def test_symlink_escape_is_skipped_with_reason_and_scan_completes(tmp_path: Path) -> None:
    # Given: a vault containing one real page and a symlink pointing outside.
    root = tmp_path / "vault"
    root.mkdir()
    _ = _write_md(root, "ok.md", "safe\n")
    outside = tmp_path / "outside.md"
    _ = outside.write_text("escaped\n", encoding="utf-8")
    (root / "escape.md").symlink_to(outside)
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: scan walks the tree.
    items = list(adapter.scan(None))

    # Then: the real page is delivered, the symlink is skipped with a reason, scan completes.
    assert _delivered(items) == [("ok.md", b"safe\n")]
    skipped = [meta for _ref, _body, meta in items if "skip_reason" in meta]
    assert skipped
    assert any(meta.get("skip_reason") == "symlink" for meta in skipped)
    assert any(meta.get("relative_path") == "escape.md" for meta in skipped)
    assert outside.read_text(encoding="utf-8") == "escaped\n"
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_denied_path_is_skipped_and_scan_completes(tmp_path: Path) -> None:
    # Given: a credential-class file beside an admissible markdown page.
    root = tmp_path / "vault"
    root.mkdir()
    _ = _write_md(root, "ok.md", "keep\n")
    _ = (root / "private.key").write_bytes(b"must-not-read")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: scan walks the tree.
    items = list(adapter.scan(None))

    # Then: the key is skipped with a denied-path reason and the page is still delivered.
    assert _delivered(items) == [("ok.md", b"keep\n")]
    skipped = [meta for _ref, _body, meta in items if "skip_reason" in meta]
    assert any(
        meta.get("skip_reason") == "denied-path" and meta.get("relative_path") == "private.key"
        for meta in skipped
    )


def test_nested_git_directory_is_excluded_at_any_depth(tmp_path: Path) -> None:
    # Given: .git metadata at the root and nested one directory down.
    root = tmp_path / "vault"
    _ = _write_md(root, "note.md", "tracked\n")
    _ = _write_md(root, "nested/page.md", "also\n")
    git_root = root / ".git"
    git_root.mkdir()
    _ = (git_root / "COMMIT_EDITMSG").write_text("secret", encoding="utf-8")
    nested_git = root / "nested" / ".git"
    nested_git.mkdir()
    _ = (nested_git / "config").write_text("secret", encoding="utf-8")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: scan walks the tree.
    items = list(adapter.scan(None))

    # Then: only non-git markdown is delivered; no .git path appears at any depth.
    delivered_uris = [uri for uri, _body in _delivered(items)]
    assert delivered_uris == ["nested/page.md", "note.md"]
    for ref, _body, meta in items:
        assert ".git" not in ref.source_uri.split("/")
        assert ".git" not in meta.get("relative_path", "").split("/")


def test_per_file_cursor_token_uses_mtime_ns_size_sha256(tmp_path: Path) -> None:
    # Given: one markdown file with known bytes.
    root = tmp_path / "vault"
    path = _write_md(root, "note.md", "body\n")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = f"{stat.st_mtime_ns}:{stat.st_size}:{digest}"
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: the file is scanned.
    items = list(adapter.scan(None))

    # Then: the per-file cursor token is mtime_ns:size:sha256.
    assert len(items) == 1
    _ref, _body, meta = items[0]
    assert meta.get("cursor") == expected


def test_scan_does_not_follow_symlinks_when_statting(tmp_path: Path) -> None:
    # Given: a symlink escape whose target is a directory outside the vault.
    root = tmp_path / "vault"
    root.mkdir()
    _ = _write_md(root, "ok.md", "x\n")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    _ = (outside_dir / "secret.md").write_text("nope\n", encoding="utf-8")
    (root / "leak").symlink_to(outside_dir, target_is_directory=True)
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: scan walks the tree.
    items = list(adapter.scan(None))

    # Then: outside content is not ingested; the symlink is skipped; scan completes.
    assert _delivered(items) == [("ok.md", b"x\n")]
    assert any(meta.get("skip_reason") == "symlink" for _r, _b, meta in items)
    assert not any("secret.md" in ref.source_uri for ref, _b, _m in items)
    assert os.path.islink(root / "leak")


_TOKEN_A = "1:1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_TOKEN_B = "2:2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_scan_delivers_tab_filename_and_unchanged_rescan_is_zero(tmp_path: Path) -> None:
    # Given: a markdown file whose name contains a tab.
    root = tmp_path / "vault"
    relative = "a\tb.md"
    path = _write_md(root, relative, "tab-body\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: the tree is scanned, then rescanned with the returned cursor.
    items = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    resume = list(adapter.scan(cursor))

    # Then: the SourceRef URI is the exact filename, keys round-trip, resume is empty.
    assert _delivered(items) == [(relative, path.read_bytes())]
    assert items[0][0].source_uri == relative
    assert items[0][2].get("relative_path") == relative
    assert relative in decode_source_cursor(cursor)
    assert resume == []


def test_scan_delivers_newline_filename_and_unchanged_rescan_is_zero(tmp_path: Path) -> None:
    # Given: a markdown file whose name contains a newline.
    root = tmp_path / "vault"
    relative = "line\nbreak.md"
    path = _write_md(root, relative, "nl-body\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="fixture")

    # When: the tree is scanned, then rescanned with the returned cursor.
    items = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    resume = list(adapter.scan(cursor))

    # Then: the SourceRef URI is the exact filename, keys round-trip, resume is empty.
    assert _delivered(items) == [(relative, path.read_bytes())]
    assert items[0][0].source_uri == relative
    assert items[0][2].get("relative_path") == relative
    assert relative in decode_source_cursor(cursor)
    assert resume == []


def test_cursor_codec_roundtrips_tab_collision_keys() -> None:
    # Given: keys the tab/newline codec would smash, plus colon/backslash/unicode.
    original = {
        "a": _TOKEN_A,
        "a\tb.md": _TOKEN_B,
        "line\nbreak.md": _TOKEN_A,
        "col:on.md": _TOKEN_B,
        "back\\slash.md": _TOKEN_A,
        "위키.md": _TOKEN_B,
    }

    # When: the map is dumped and parsed.
    roundtrip = decode_source_cursor(encode_source_cursor(original))

    # Then: both keys and tokens survive losslessly.
    assert roundtrip == original


def test_parse_cursor_rejects_malformed_payload() -> None:
    # Given: a cursor string that is not a valid encoded map.
    # When / Then: parse fails closed with the typed cursor error.
    with pytest.raises(MarkdownVaultError):
        _ = decode_source_cursor("not-a-cursor")


def test_missing_root_preserves_resume_and_reports_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "source"
    _ = _write_md(root, "note.md", "retained\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="notes")
    _ = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    _ = root.rename(tmp_path / "offline")

    items = list(MarkdownVaultAdapter(root=root, source_id="notes").scan(cursor))

    assert len(items) == 1
    assert items[0][2].get("skip_reason") == "source-unavailable"
    resumed = MarkdownVaultAdapter(root=root, source_id="notes")
    _ = list(resumed.scan(cursor))
    assert resumed.next_cursor() == cursor


def test_disappearance_is_one_observation_not_remote_erasure(tmp_path: Path) -> None:
    root = tmp_path / "source"
    path = _write_md(root, "note.md", "retained elsewhere\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="notes", observe_deletions=True)
    _ = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    _ = path.rename(tmp_path / "retained.md")

    items = list(adapter.scan(cursor))

    assert len(items) == 1
    assert items[0][0].source_uri == "note.md"
    assert items[0][2].get("skip_reason") == "source-deleted"
    assert items[0][1] == b""
    assert (tmp_path / "retained.md").read_text() == "retained elsewhere\n"
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_deletion_observations_default_off_preserves_prior_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "source"
    page = _write_md(root, "note.md", "retained\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="notes")
    _ = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    _ = page.rename(tmp_path / "retained.md")

    assert list(adapter.scan(cursor)) == []

    assert adapter.next_cursor() == cursor


def test_blocked_ancestor_does_not_become_disappearance(tmp_path: Path) -> None:
    root = tmp_path / "source"
    _ = _write_md(root, "nested/note.md", "retained\n")
    adapter = MarkdownVaultAdapter(root=root, source_id="notes", observe_deletions=True)
    _ = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    _ = (root / "nested").rename(tmp_path / "retained")
    (root / "nested").symlink_to(tmp_path / "retained", target_is_directory=True)

    items = list(adapter.scan(cursor))

    assert any(meta.get("skip_reason") == "symlink" for _ref, _body, meta in items)
    assert not any(meta.get("skip_reason") == "source-deleted" for _ref, _body, meta in items)
    assert decode_source_cursor(adapter.next_cursor())["nested/note.md"] == (
        decode_source_cursor(cursor)["nested/note.md"]
    )
