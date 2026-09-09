"""Ambiguous archive paths must fail before extraction writes any files."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

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
        GenerationRestoreSanitizer._extract(archive, destination)
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
        GenerationRestoreSanitizer._extract(archive, destination)
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
    GenerationRestoreSanitizer._extract(archive, destination)
    assert (destination / 'wiki/page.md').read_bytes() == b'kept'


@pytest.mark.parametrize('kind', ['tar', 'directory'])
@pytest.mark.parametrize('limit,value', [('_MAX_RESTORE_MEMBERS', 1),
    ('_MAX_RESTORE_FILE_BYTES', 3), ('_MAX_RESTORE_TOTAL_BYTES', 7)])
def test_restore_budget_rejection_precedes_output(
    tmp_path: Path, monkeypatch, kind: str, limit: str, value: int,
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
            (archive / name).write_bytes(b'data')
    destination = tmp_path / 'extracted'
    destination.mkdir()
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_BUDGET_EXCEEDED'):
        GenerationRestoreSanitizer._extract(archive, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('replacement', ['symlink', 'file', 'fifo'])
def test_directory_restore_refuses_file_replaced_after_stat(tmp_path: Path, monkeypatch, replacement: str) -> None:
    archive = tmp_path / 'archive'
    archive.mkdir()
    source = archive / 'memory.md'
    source.write_bytes(b'original')
    outside = tmp_path / 'outside.md'
    outside.write_bytes(b'replaced')
    destination = tmp_path / 'extracted'
    destination.mkdir()
    original_stat = Path.stat
    calls = 0

    def swap_after_stat(path, *args, **kwargs):
        nonlocal calls
        result = original_stat(path, *args, **kwargs)
        if path == source and kwargs.get('follow_symlinks') is False:
            calls += 1
            if calls == 2:
                path.unlink()
                if replacement == 'symlink':
                    path.symlink_to(outside)
                elif replacement == 'fifo':
                    import os
                    os.mkfifo(path)
                else:
                    path.write_bytes(b'replaced')
        return result

    monkeypatch.setattr(Path, 'stat', swap_after_stat)
    with pytest.raises(RestoreError, match='RESTORE_ARCHIVE_UNSAFE'):
        GenerationRestoreSanitizer._extract(archive, destination)
    assert not (destination / 'memory.md').exists()
    assert outside.read_bytes() == b'replaced'
