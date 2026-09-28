"""Bundled runtimes cannot silently keep dependencies outside the release."""

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from tests.deploy_fixtures import load_deploy


@runtime_checkable
class RuntimeBundle(Protocol):
    def bundle_runtime(self, source: Path, destination: Path) -> None: ...
    def runtime_digest(self, root: Path) -> str: ...
    def release_identity(self, wheel: bytes, requirements: bytes, runtime_sha256: str, recipe_sha256: str) -> str: ...


def runtime_api() -> RuntimeBundle:
    module = load_deploy("bundle_python_runtime.py")
    assert isinstance(module, RuntimeBundle)
    return module


bundle = runtime_api().bundle_runtime


def test_release_identity_binds_runtime_bytes_and_not_staging_path(tmp_path: Path):
    api = runtime_api()
    source = tmp_path / "source"
    source.mkdir()
    _ = (source / "python").write_bytes(b"runtime one")
    target = tmp_path / "target"
    bundle(source, target)
    first = api.runtime_digest(source)
    assert api.runtime_digest(target) == first
    identity = api.release_identity(b"wheel", b"locked requirements", first, "recipe-one")
    _ = (target / "python").write_bytes(b"runtime two")
    second = api.runtime_digest(target)
    assert second != first
    assert api.release_identity(b"wheel", b"locked requirements", second, "recipe-one") != identity
    assert api.release_identity(b"wheel", b"locked requirements", first, "recipe-two") != identity


@pytest.mark.parametrize("external", [False, True])
def test_runtime_links_are_internal(tmp_path: Path, external: bool):
    source = tmp_path / "source"
    source.mkdir()
    _ = (source / "python").write_bytes(b"binary fixture")
    (source / "alias").symlink_to("../outside" if external else "python")
    _ = (tmp_path / "outside").write_bytes(b"outside")
    target = tmp_path / "target"
    if external:
        with pytest.raises(ValueError, match="PYTHON_RUNTIME_EXTERNAL_LINK"):
            bundle(source, target)
        assert not target.exists()
    else:
        bundle(source, target)
        assert (target / "alias").resolve() == target / "python"
        assert (target / "alias").read_bytes() == b"binary fixture"


def test_runtime_refuses_fifo(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    with pytest.raises(ValueError, match="PYTHON_RUNTIME_SPECIAL_FILE"):
        bundle(source, tmp_path / "target")
