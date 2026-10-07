"""Installed bytes and transitive runtime links must match the accepted candidate."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from sb.effect_values import JsonObject


@runtime_checkable
class ReleaseModule(Protocol):
    def inventory(self, root: Path) -> JsonObject: ...
    def verify(self, root: Path, manifest: Path, expected_sha256: str) -> JsonObject: ...


spec = importlib.util.spec_from_file_location("check-release-contents", Path(__file__).resolve().parents[1] / "deploy/check-release-contents.py")
assert spec is not None and spec.loader is not None
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)
assert isinstance(API, ReleaseModule)
inventory = API.inventory
verify = API.verify


@pytest.mark.parametrize("change", ["content", "mode", "add", "remove", "link", "external"])
def test_rejects_candidate_changes(tmp_path: Path, change: str):
    root = tmp_path / "release"
    root.mkdir()
    code = root / "app.js"
    _ = code.write_text("accepted")
    outside = tmp_path / "interpreter"
    _ = outside.write_text("runtime")
    (root / "node").symlink_to(outside)
    link = root / "entry"
    link.symlink_to("app.js")
    manifest = tmp_path / "inventory.json"
    raw = json.dumps(inventory(root)).encode()
    _ = manifest.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert verify(root, manifest, digest)["matches"]
    if change == "content":
        _ = code.write_text("tampered")
    elif change == "mode":
        code.chmod(0o700)
    elif change == "add":
        _ = (root / "injected.js").write_text("injected")
    elif change == "remove":
        link.unlink()
    elif change == "link":
        link.unlink()
        link.symlink_to("node")
    else:
        _ = outside.write_text("changed")
    assert not verify(root, manifest, digest)["matches"]
    _ = manifest.write_text("{}")
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        _ = verify(root, manifest, digest)


@pytest.mark.parametrize("kind", ["directory", "fifo", "broken"])
def test_rejects_unbounded_or_invalid_dependencies(tmp_path: Path, kind: str):
    root = tmp_path / "release"
    root.mkdir()
    if kind == "directory":
        (root / "dependencies").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(root / "pipe")
    else:
        (root / "missing").symlink_to("absent")
    with pytest.raises((ValueError, FileNotFoundError)):
        _ = inventory(root)
