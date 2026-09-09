"""Observed metadata must retain whole archives without escaping the cache."""

import json
import runpy
from pathlib import Path

import pytest

snapshot = runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/snapshot-observed-uv-cache.py"))["snapshot_cache"]


def test_snapshot_copies_archive_and_relocates_index_link(tmp_path):
    cache = tmp_path / "cache"
    archive = cache / "archive-v0" / "package"
    archive.mkdir(parents=True)
    (archive / "seen").write_text("seen")
    (archive / "sibling").write_text("needed package sibling")
    (cache / "index").symlink_to(archive)
    trace = tmp_path / "trace"
    trace.write_text('\n'.join(json.dumps(str(path)) for path in [archive / "seen", cache / "index"]))
    target = tmp_path / "snapshot"
    report = snapshot(trace, cache, target)
    assert (target / "index" / "sibling").read_text() == "needed package sibling"
    assert (target / "index").resolve().is_relative_to(target)
    assert report["offline_completeness_verified"] is False
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        snapshot(trace, cache, target)


def test_snapshot_refuses_external_link(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "outside").symlink_to(tmp_path)
    trace = tmp_path / "trace"
    trace.write_text(json.dumps(str(cache / "outside")))
    with pytest.raises(ValueError, match="ESCAPES_ROOT"):
        snapshot(trace, cache, tmp_path / "snapshot")
