"""Filesystem discovery ports used by the markdown vault connector."""

from __future__ import annotations

from pathlib import Path

import pytest

from sb.connectors.discovery import (
    SOURCE_DISCOVERY_REQUEST_V1,
    SourceDiscoveryError,
    SourceDiscoveryRequestV1,
    discover_source,
)
from sb.connectors.fs_safety import is_denied_source_path


def _request(root: Path) -> SourceDiscoveryRequestV1:
    return SourceDiscoveryRequestV1.from_mapping(
        {
            "request_version": SOURCE_DISCOVERY_REQUEST_V1,
            "source_name": "me-wiki",
            "source_root": str(root.resolve()),
        }
    )


def test_discover_source_lists_markdown_without_git_or_denied(tmp_path: Path) -> None:
    # Given: a source tree with markdown, nested .git metadata, and a deny-class file.
    root = tmp_path / "source"
    notes = root / "notes"
    notes.mkdir(parents=True)
    _ = (notes / "alpha.md").write_text("body", encoding="utf-8")
    git_dir = root / "deep" / ".git"
    git_dir.mkdir(parents=True)
    _ = (git_dir / "config").write_text("vcs", encoding="utf-8")
    _ = (root / "note.md").write_text("root body", encoding="utf-8")

    # When: metadata-only discovery runs.
    manifest = discover_source(_request(root))

    # Then: only regular allowed files are listed, sorted, with bound path digests.
    assert [entry.relative_path for entry in manifest.entries] == [
        "note.md",
        "notes/alpha.md",
    ]
    assert manifest.body_reads == "0"
    assert all(len(entry.path_digest) == 64 for entry in manifest.entries)


def test_discover_source_rejects_denied_path(tmp_path: Path) -> None:
    # Given: a source root that contains a credential-class path.
    root = tmp_path / "source"
    root.mkdir()
    _ = (root / "private.key").write_text("nope", encoding="utf-8")
    assert is_denied_source_path("private.key")

    # When / Then: discovery fail-closes on the deny class.
    with pytest.raises(SourceDiscoveryError, match="deny-class"):
        _ = discover_source(_request(root))
