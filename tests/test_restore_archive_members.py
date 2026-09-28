"""Ambiguous archive paths must fail before extraction writes any files."""
from __future__ import annotations

import io
import tarfile
from collections.abc import Callable, Iterable
from os import PathLike
from pathlib import Path
from typing import Literal

import pytest

from sb.restore import GenerationRestoreSanitizer, RestoreError


@pytest.mark.parametrize('second_name', ['wiki/page.md', './wiki/page.md', 'wiki//page.md'])
def test_restore_rejects_duplicate_normalized_member(tmp_path: Path, second_name: str) -> None:
    archive = tmp_path / 'duplicate.tar'
    with tarfile.open(archive, 'w') as bundle:
        for name, content in [('wiki/page.md', b'original'), (second_name, b'replacement')]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer.extract(archive, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('names', [('wiki', 'wiki/page.md'), ('wiki/page.md', 'wiki')])
def test_restore_rejects_file_as_parent_before_writing(tmp_path: Path, names: tuple[str, str]) -> None:
    archive = tmp_path / 'conflict.tar'
    with tarfile.open(archive, 'w') as bundle:
        for name in names:
            member = tarfile.TarInfo(name)
            member.size = 1
            bundle.addfile(member, io.BytesIO(b'x'))
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer.extract(archive, destination)
    assert list(destination.iterdir()) == []


def test_restore_extracts_unambiguous_archive(tmp_path: Path) -> None:
    archive = tmp_path / 'valid.tar'
    with tarfile.open(archive, 'w') as bundle:
        directory = tarfile.TarInfo('./wiki')
        directory.type = tarfile.DIRTYPE
        bundle.addfile(directory)
        member = tarfile.TarInfo('wiki/page.md')
        member.size = 4
        bundle.addfile(member, io.BytesIO(b'kept'))
    destination = tmp_path / 'extracted'
    destination.mkdir()
    GenerationRestoreSanitizer.extract(archive, destination)
    assert (destination / 'wiki/page.md').read_bytes() == b'kept'


@pytest.mark.parametrize('kind', ['tar', 'directory'])
@pytest.mark.parametrize('limit,value', [('_MAX_RESTORE_MEMBERS', 1),
    ('_MAX_RESTORE_FILE_BYTES', 3), ('_MAX_RESTORE_TOTAL_BYTES', 7)])
def test_restore_budget_rejection_precedes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, limit: str, value: int,
) -> None:
    from sb import restore

    monkeypatch.setattr(restore, limit, value, raising=False)
    archive = tmp_path / 'archive'
    if kind == 'tar':
        with tarfile.open(archive, 'w') as bundle:
            for name in ['one.md', 'two.md']:
                member = tarfile.TarInfo(name)
                member.size = 4
                bundle.addfile(member, io.BytesIO(b'data'))
    else:
        archive.mkdir()
        for name in ['one.md', 'two.md']:
            _ = (archive / name).write_bytes(b'data')
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_BUDGET_EXCEEDED'):
        GenerationRestoreSanitizer.extract(archive, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('replacement', ['symlink', 'file', 'fifo'])
def test_directory_restore_refuses_file_replaced_after_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str) -> None:
    archive = tmp_path / 'archive'
    archive.mkdir()
    source = archive / 'memory.md'
    _ = source.write_bytes(b'original')
    outside = tmp_path / 'outside.md'
    _ = outside.write_bytes(b'replaced')
    destination = tmp_path / 'extracted'
    destination.mkdir()
    original_stat = Path.stat
    calls = 0

    def swap_after_stat(path: Path, *, follow_symlinks: bool = True):
        nonlocal calls
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == source and follow_symlinks is False:
            calls += 1
            if calls == 2:
                path.unlink()
                if replacement == 'symlink':
                    path.symlink_to(outside)
                elif replacement == 'fifo':
                    import os
                    os.mkfifo(path)
                else:
                    _ = path.write_bytes(b'replaced')
        return result

    monkeypatch.setattr(Path, 'stat', swap_after_stat)
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer.extract(archive, destination)
    assert not (destination / 'memory.md').exists()
    assert outside.read_bytes() == b'replaced'


@pytest.mark.parametrize('link_type', ['symlink', 'hardlink'])
def test_restore_refuses_linked_tar_input(tmp_path: Path, link_type: str) -> None:
    import os

    original = tmp_path / 'original.tar'
    with tarfile.open(original, 'w') as bundle:
        member = tarfile.TarInfo('wiki/page.md')
        member.size = 4
        bundle.addfile(member, io.BytesIO(b'kept'))
    archive = tmp_path / 'input.tar'
    if link_type == 'symlink':
        archive.symlink_to(original)
    else:
        os.link(original, archive)
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer.extract(archive, destination)
    assert list(destination.iterdir()) == []


def test_restore_refuses_tar_changed_during_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / 'input.tar'
    with tarfile.open(archive, 'w') as bundle:
        member = tarfile.TarInfo('wiki/page.md')
        member.size = 4
        bundle.addfile(member, io.BytesIO(b'kept'))
    extractall = tarfile.TarFile.extractall

    def change_after_extract(bundle: tarfile.TarFile, path: str | PathLike[str] = ".", members: Iterable[tarfile.TarInfo] | None = None, *, numeric_owner: bool = False, filter: Literal["fully_trusted", "tar", "data"] | Callable[[tarfile.TarInfo, str], tarfile.TarInfo | None] | None = None) -> None:
        extractall(bundle, path, members, numeric_owner=numeric_owner, filter=filter)
        with archive.open('ab') as stream:
            _ = stream.write(b'changed')

    monkeypatch.setattr(tarfile.TarFile, 'extractall', change_after_extract)
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer.extract(archive, destination)
