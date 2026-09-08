"""Private vector staging recovery must preserve live writers and unrelated files."""
from __future__ import annotations

import os
import select
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import sb.vector_cleanup as cleanup
from sb.vector_rebuild import EmbeddingUnavailable, publish_vectors


def _build(path: Path, lock_fd: int) -> int:
    del lock_fd
    _ = path.write_bytes(b"complete replacement")
    return 1


def _fixture(root: Path) -> Path:
    folder = root / ".sb"
    folder.mkdir(mode=0o700)
    _ = (folder / "vectors.db").write_bytes(b"previous database")
    return folder


def _orphan(folder: Path, name: str = ".vectors-abcdefgh.db") -> Path:
    path = folder / name
    _ = path.write_bytes(b"private source-derived bytes")
    path.chmod(0o600)
    return path


def _no_readers(identities: set[tuple[int, int]]) -> None:
    del identities


def test_vector_rebuild_rejects_symlinked_private_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "vectors.db"
    _ = marker.write_bytes(b"unrelated database")
    root = tmp_path / "vault"
    root.mkdir(mode=0o700)
    (root / ".sb").symlink_to(outside, target_is_directory=True)
    with pytest.raises(EmbeddingUnavailable):
        _ = publish_vectors(root, _build)
    assert marker.read_bytes() == b"unrelated database"
    assert list(outside.iterdir()) == [marker]


def test_abandoned_vector_files_and_sidecars_are_recovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _fixture(tmp_path)
    stale = [_orphan(folder, ".vectors-abcdefgh.db" + suffix)
             for suffix in ("", "-journal", "-wal", "-shm")]
    unrelated = _orphan(folder, ".vectors-not-owned.db")
    # Deterministic complete reader inventory, independent of host /proc policy.
    monkeypatch.setattr(cleanup, "_require_unused", _no_readers)
    assert publish_vectors(tmp_path, _build) == 1
    assert not any(path.exists() for path in stale)
    assert unrelated.read_bytes() == b"private source-derived bytes"
    assert (folder / "vectors.db").read_bytes() == b"complete replacement"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "public"])
def test_unsafe_orphan_refuses_rebuild_before_any_disposal(tmp_path: Path, kind: str) -> None:
    folder = _fixture(tmp_path)
    safe = _orphan(folder, ".vectors-aaaaaaaa.db")
    unsafe = folder / ".vectors-zzzzzzzz.db"
    outside = tmp_path / "unrelated"
    _ = outside.write_bytes(b"do not change")
    if kind == "symlink":
        unsafe.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, unsafe)
    elif kind == "directory":
        unsafe.mkdir()
    else:
        _ = unsafe.write_bytes(b"public")
        unsafe.chmod(0o644)
    with pytest.raises(EmbeddingUnavailable):
        _ = publish_vectors(tmp_path, _build)
    assert safe.exists() and os.path.lexists(unsafe)
    assert outside.read_bytes() == b"do not change"
    assert (folder / "vectors.db").read_bytes() == b"previous database"


@pytest.mark.skipif(not Path('/proc/self/fd').is_dir(), reason="requires proc descriptor evidence")
def test_open_orphan_is_preserved_until_reader_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _fixture(tmp_path)
    orphan = _orphan(folder)
    with orphan.open("rb") as reader:
        with pytest.raises(EmbeddingUnavailable, match="in use"):
            _ = publish_vectors(tmp_path, _build)
        assert reader.read() == b"private source-derived bytes"
        assert orphan.exists()
        assert (folder / "vectors.db").read_bytes() == b"previous database"
    monkeypatch.setattr(cleanup, "_require_unused", _no_readers)
    assert publish_vectors(tmp_path, _build) == 1
    assert not orphan.exists()


def test_unverifiable_readers_preserve_orphans_but_allow_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    folder = _fixture(tmp_path)
    orphan = _orphan(folder)

    def unverifiable(identities: set[tuple[int, int]]) -> None:
        del identities
        raise cleanup._UnverifiableReaders()  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(cleanup, "_require_unused", unverifiable)
    assert publish_vectors(tmp_path, _build) == 1
    assert orphan.read_bytes() == b"private source-derived bytes"
    assert "cleanup deferred" in caplog.text


def test_directory_replacement_during_build_cannot_redirect_publication(tmp_path: Path) -> None:
    folder = _fixture(tmp_path)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    marker = outside / "vectors.db"
    _ = marker.write_bytes(b"unrelated database")
    moved = tmp_path / "previous-sb"

    def move_directory(path: Path, lock_fd: int) -> int:
        _ = _build(path, lock_fd)
        _ = folder.rename(moved)
        folder.symlink_to(outside, target_is_directory=True)
        return 1

    with pytest.raises(EmbeddingUnavailable, match="directory changed"):
        _ = publish_vectors(tmp_path, move_directory)
    assert marker.read_bytes() == b"unrelated database"
    assert (moved / "vectors.db").read_bytes() == b"previous database"
    assert not list(moved.glob(".vectors-*.db"))


def test_post_replace_sync_failure_reports_actual_publication_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _fixture(tmp_path)
    fsync = os.fsync

    def fail_directory(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory sync failure")
        fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_directory)
        with pytest.raises(EmbeddingUnavailable, match="replaced; durability unconfirmed"):
            _ = publish_vectors(tmp_path, _build)
    assert (folder / "vectors.db").read_bytes() == b"complete replacement"
    assert publish_vectors(tmp_path, _build) == 1


def test_interrupted_cleanup_resumes_remaining_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _fixture(tmp_path)
    first = _orphan(folder, ".vectors-aaaaaaaa.db")
    second = _orphan(folder, ".vectors-bbbbbbbb.db")
    monkeypatch.setattr(cleanup, "_require_unused", _no_readers)
    unlink = os.unlink

    def fail_second(path: str, *, dir_fd: int | None = None) -> None:
        if path == second.name:
            raise OSError("injected unlink failure")
        unlink(path, dir_fd=dir_fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_second)
        with pytest.raises(EmbeddingUnavailable):
            _ = publish_vectors(tmp_path, _build)
    assert not first.exists() and second.exists()
    assert (folder / "vectors.db").read_bytes() == b"previous database"
    assert publish_vectors(tmp_path, _build) == 1
    assert not second.exists()


def test_child_holds_writer_lease_after_parent_exit(tmp_path: Path) -> None:
    folder = _fixture(tmp_path)
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    program = """
import os, subprocess, sys
from pathlib import Path
from sb.vector_rebuild import publish_vectors
def build(path, lock_fd):
    path.write_bytes(b'private unfinished source')
    child = ('import os; '
             + f'os.write({sys.argv[2]}, b"r"); os.read({sys.argv[3]}, 1); '
             + f'os.close({lock_fd}); os.write({sys.argv[2]}, b"d")')
    subprocess.Popen([sys.executable, '-c', child],
        pass_fds=(lock_fd, int(sys.argv[2]), int(sys.argv[3])),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(17)
publish_vectors(Path(sys.argv[1]), build)
"""
    try:
        done = subprocess.run([sys.executable, "-c", program, str(tmp_path), str(ready_write), str(release_read)],
                              pass_fds=(ready_write, release_read), capture_output=True, timeout=15, check=False)
        assert done.returncode == 17, done.stderr
        assert select.select([ready_read], [], [], 10)[0]
        assert os.read(ready_read, 1) == b"r"
        before = set(folder.glob(".vectors-*.db"))
        assert len(before) == 1
        with pytest.raises(EmbeddingUnavailable, match="already in progress"):
            _ = publish_vectors(tmp_path, _build)
        assert set(folder.glob(".vectors-*.db")) == before
        assert (folder / "vectors.db").read_bytes() == b"previous database"
        _ = os.write(release_write, b"x")
        assert select.select([ready_read], [], [], 10)[0]
        assert os.read(ready_read, 1) == b"d"
        assert publish_vectors(tmp_path, _build) == 1
        assert (folder / "vectors.db").read_bytes() == b"complete replacement"
    finally:
        for fd in (ready_read, ready_write, release_read, release_write):
            os.close(fd)


def test_private_root_allows_normal_group_umask_on_inner_directory(tmp_path: Path) -> None:
    folder = _fixture(tmp_path)
    folder.chmod(0o775)
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert publish_vectors(tmp_path, _build) == 1
    assert stat.S_IMODE((folder / "vectors.db").stat().st_mode) == 0o600


def test_public_vault_root_refuses_vector_writes(tmp_path: Path) -> None:
    folder = _fixture(tmp_path)
    tmp_path.chmod(0o775)
    try:
        with pytest.raises(EmbeddingUnavailable, match="unsafe vector vault root"):
            _ = publish_vectors(tmp_path, _build)
        assert (folder / "vectors.db").read_bytes() == b"previous database"
    finally:
        tmp_path.chmod(0o700)
