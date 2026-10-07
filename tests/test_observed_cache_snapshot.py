"""Observed metadata must retain whole archives without escaping the cache."""

import importlib.util
import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from sb.effect_values import JsonObject


@runtime_checkable
class SnapshotModule(Protocol):
    def snapshot_cache(self, trace: Path, cache: Path, destination: Path) -> JsonObject: ...


spec = importlib.util.spec_from_file_location("snapshot-observed-uv-cache", Path(__file__).resolve().parents[1] / "deploy/snapshot-observed-uv-cache.py")
assert spec is not None and spec.loader is not None
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)
assert isinstance(API, SnapshotModule)
snapshot = API.snapshot_cache


def test_snapshot_copies_archive_and_relocates_index_link(tmp_path: Path):
    cache = tmp_path / "cache"
    archive = cache / "archive-v0" / "package"
    archive.mkdir(parents=True)
    _ = (archive / "seen").write_text("seen")
    _ = (archive / "sibling").write_text("needed package sibling")
    (cache / "index").symlink_to(archive)
    trace = tmp_path / "trace"
    _ = trace.write_text('\n'.join(json.dumps(str(path)) for path in [archive / "seen", cache / "index"]))
    target = tmp_path / "snapshot"
    report = snapshot(trace, cache, target)
    assert (target / "index" / "sibling").read_text() == "needed package sibling"
    assert (target / "index").resolve().is_relative_to(target)
    assert report["offline_completeness_verified"] is False
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        _ = snapshot(trace, cache, target)


def test_snapshot_refuses_external_link(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "outside").symlink_to(tmp_path)
    trace = tmp_path / "trace"
    _ = trace.write_text(json.dumps(str(cache / "outside")))
    with pytest.raises(ValueError, match="ESCAPES_ROOT"):
        _ = snapshot(trace, cache, tmp_path / "snapshot")
