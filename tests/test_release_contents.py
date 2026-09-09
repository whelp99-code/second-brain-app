"""Installed bytes and transitive runtime links must match the accepted candidate."""

import hashlib
import json
import os
import runpy
from pathlib import Path

import pytest

API = runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/check-release-contents.py"))


@pytest.mark.parametrize("change", ["content", "mode", "add", "remove", "link", "external"])
def test_rejects_candidate_changes(tmp_path, change):
    root = tmp_path / "release"
    root.mkdir()
    code = root / "app.js"
    code.write_text("accepted")
    outside = tmp_path / "interpreter"
    outside.write_text("runtime")
    (root / "node").symlink_to(outside)
    link = root / "entry"
    link.symlink_to("app.js")
    manifest = tmp_path / "inventory.json"
    raw = json.dumps(API["inventory"](root)).encode()
    manifest.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert API["verify"](root, manifest, digest)["matches"]
    if change == "content":
        code.write_text("tampered")
    elif change == "mode":
        code.chmod(0o700)
    elif change == "add":
        (root / "injected.js").write_text("injected")
    elif change == "remove":
        link.unlink()
    elif change == "link":
        link.unlink()
        link.symlink_to("node")
    else:
        outside.write_text("changed")
    assert not API["verify"](root, manifest, digest)["matches"]
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        API["verify"](root, manifest, digest)


@pytest.mark.parametrize("kind", ["directory", "fifo", "broken"])
def test_rejects_unbounded_or_invalid_dependencies(tmp_path, kind):
    root = tmp_path / "release"
    root.mkdir()
    if kind == "directory":
        (root / "dependencies").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(root / "pipe")
    else:
        (root / "missing").symlink_to("absent")
    with pytest.raises((ValueError, FileNotFoundError)):
        API["inventory"](root)
