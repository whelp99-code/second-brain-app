from pathlib import Path

import pytest

from sb.generation_runtime_models import GenerationMutationError
from sb.generation_staging import copy_pending_inbox


def test_pending_inbox_rejects_hardlink_without_copying(tmp_path: Path) -> None:
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    (source / 'inbox').mkdir(parents=True)
    outside = tmp_path / 'outside'
    _ = outside.write_bytes(b'outside shared bytes')
    (source / 'inbox' / 'linked.md').hardlink_to(outside)
    with pytest.raises(GenerationMutationError, match='GENERATION_SOURCE_UNSAFE'):
        copy_pending_inbox(source, destination, tmp_path / 'state')
    assert not destination.exists()
    assert outside.read_bytes() == b'outside shared bytes'


def test_pending_inbox_copies_regular_files_and_excludes_completed(tmp_path: Path) -> None:
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    for name in ['pending/note.md', '.done/old.md', '.requests/request.json']:
        path = source / 'inbox' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(name)
    copy_pending_inbox(source, destination, tmp_path / 'state')
    assert (destination / 'inbox/pending/note.md').read_text() == 'pending/note.md'
    assert not (destination / 'inbox/.done').exists()
    assert not (destination / 'inbox/.requests').exists()


@pytest.mark.parametrize('replacement', ['symlink', 'fifo', 'parent-symlink'])
def test_pending_file_replacement_between_scan_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str,
) -> None:
    import os

    from sb import generation_staging

    source, destination = tmp_path / 'source', tmp_path / 'destination'
    folder = source / 'inbox/nested'
    folder.mkdir(parents=True)
    path = folder / 'note.md'
    _ = path.write_text('original')
    outside = tmp_path / 'outside'
    outside.mkdir()
    _ = (outside / 'note.md').write_text('outside')
    original = generation_staging.read_pending_file

    def replace(inbox: Path, relative: Path) -> bytes:
        path.unlink()
        if replacement == 'parent-symlink':
            folder.rmdir()
            folder.symlink_to(outside, target_is_directory=True)
        elif replacement == 'symlink':
            path.symlink_to(outside / 'note.md')
        else:
            os.mkfifo(path)
        return original(inbox, relative)

    monkeypatch.setattr(generation_staging, 'read_pending_file', replace)
    with pytest.raises(GenerationMutationError, match='GENERATION_SOURCE_UNSAFE'):
        copy_pending_inbox(source, destination, tmp_path / 'state')
    assert not destination.exists()
