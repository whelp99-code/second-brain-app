"""Managed Git copies must be decoded or fail closed before disposal proof."""

from __future__ import annotations

import secrets
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sb.managed_copy_disposal import copy_inventory
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_file_inspection import ManagedInspectionError
from sb.managed_git import DISPOSING_PREFIX, git_directories, inspect_git_directory
from sb.managed_surface_scan import scan_managed_surfaces
from sb.provider_surface_files import scan_file_surface
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.provider_surface_specs import PROVIDER_SURFACE_SPECS


def backup(root: Path, needle: bytes, *, packed: bool = False) -> Path:
    repository = root / "renamed-backup"
    _ = subprocess.run(["git", "init", "-q", "--bare", str(repository)], check=True)
    written = subprocess.run(["git", f"--git-dir={repository}", "hash-object", "-w", "--stdin"],
                             input=needle, check=True, capture_output=True)
    if packed:
        _ = subprocess.run(["git", f"--git-dir={repository}", "update-ref", "refs/tags/retained",
                            written.stdout.decode().strip()], check=True, capture_output=True)
        _ = subprocess.run(["git", f"--git-dir={repository}", "repack", "-ad"], check=True,
                           capture_output=True)
        _ = subprocess.run(["git", f"--git-dir={repository}", "prune-packed"], check=True)
    return repository


@pytest.mark.parametrize("packed", [False, True])
def test_inventory_inspects_decoded_nested_backup_objects(tmp_path: Path, packed: bool) -> None:
    # Given: compressible runtime content and a Git directory with an arbitrary name.
    needle = secrets.token_hex(32).encode() * 8
    root = tmp_path / "backups"
    root.mkdir()
    repository = backup(root, needle, packed=packed)
    assert all(needle not in file.read_bytes() for file in repository.rglob("*") if file.is_file())
    # When: every inventory boundary inspects the managed backup.
    physical = scan_managed_surfaces((root,), (needle,))
    layout = ProviderSurfaceLayout(root, root, root, root, root, root, root, root)
    spec = next(value for value in PROVIDER_SURFACE_SPECS if value.definition.surface_id == "managed_backups")
    fixed = scan_file_surface(layout, spec, (needle,))
    # Then: none can claim clean, including the pre-activation inventory.
    assert physical.matches > 0 and physical.scan_errors == 0
    assert fixed.match_count > 0 and fixed.error_count == 0
    with pytest.raises(ManagedInspectionError, match="MANAGED_COPY_REMAINS"):
        _ = copy_inventory((root,), (needle,))


@pytest.mark.parametrize("link", [Path.symlink_to, Path.hardlink_to])
def test_unsafe_backup_is_rejected_before_any_disposal(
    tmp_path: Path, link: Callable[[Path, Path], None],
) -> None:
    # Given: a matching ordinary copy plus an unsafe Git boundary.
    needle = secrets.token_bytes(40)
    root = tmp_path / "backups"
    root.mkdir()
    repository = backup(root, needle)
    ordinary = root / "ordinary"
    _ = ordinary.write_bytes(needle)
    outside = tmp_path / "outside"
    _ = outside.write_bytes(needle)
    link(repository / "linked", outside)
    # When / Then: preflight fails closed without deleting the independent copy.
    with pytest.raises(ManagedInspectionError):
        _ = purge_matching_managed_copies((root,), (needle,))
    assert ordinary.exists() and outside.exists()
    assert scan_managed_surfaces((root,), (needle,)).scan_errors > 0


def test_git_alternates_cannot_escape_the_managed_root(tmp_path: Path) -> None:
    # Given: a Git alternate points outside the managed copy.
    repository = backup(tmp_path, secrets.token_bytes(40))
    _ = (repository / "objects/info/alternates").write_text(str(tmp_path))
    # When / Then: the inventory refuses external object authority.
    with pytest.raises(ManagedInspectionError, match="MANAGED_GIT_INDIRECTION"):
        _ = copy_inventory((tmp_path,))


@pytest.mark.parametrize("stream", [b"bad header\n", b"a" * 40 + b" blob 99\nx\n",
                                    b"a" * 40 + b" blob 1\nx!", b"a" * 40 + b" missing\n"])
def test_malformed_batch_stream_cannot_prove_absence(
    tmp_path: Path, monkeypatch: MonkeyPatch, stream: bytes,
) -> None:
    # Given: an object-reader transport returning invalid batch framing.
    repository = backup(tmp_path, secrets.token_bytes(40))
    def malformed(_root: Path) -> bytes:
        return stream
    monkeypatch.setattr("sb.managed_git._object_stream", malformed)
    # When / Then: malformed framing cannot be read as an empty object inventory.
    with pytest.raises(ManagedInspectionError, match="MANAGED_GIT_STREAM_INVALID"):
        _ = inspect_git_directory(repository, ())


def test_interrupted_git_disposal_is_fail_closed_and_replayable(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    # Given: deletion can stop after a durable rename but before all files disappear.
    needle = secrets.token_bytes(40)
    root = tmp_path / "backups"
    root.mkdir()
    _ = backup(root, needle)
    real_remove = shutil.rmtree
    def interrupt(path: Path) -> None:
        (path / "HEAD").unlink()
        raise OSError("injected disposal interruption")
    with monkeypatch.context() as context:
        context.setattr(shutil, "rmtree", interrupt)
        with pytest.raises(OSError, match="injected disposal interruption"):
            _ = purge_matching_managed_copies((root,), (needle,))
    assert any(path.name.startswith(DISPOSING_PREFIX) for path in root.iterdir())
    with pytest.raises(ManagedInspectionError, match="MANAGED_GIT_DISPOSAL_INCOMPLETE"):
        _ = copy_inventory((root,), (needle,))
    assert shutil.rmtree is real_remove
    # When: replay resumes the managed operation.
    _ = purge_matching_managed_copies((root,), (needle,))
    # Then: no incomplete Git copy can be inventoried as a successful first pass.
    assert git_directories(root) == ()
    assert scan_managed_surfaces((root,), (needle,)).matches == 0
