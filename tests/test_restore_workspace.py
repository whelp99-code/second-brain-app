from __future__ import annotations

import subprocess
import sys

import pytest

from sb.restore_workspace import restore_workspace


def test_live_restore_is_protected_from_another_process(tmp_path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    with restore_workspace(folder, 'a' * 64) as staging:
        original = staging / 'original'
        original.write_text('live restore source')
        child = subprocess.run([sys.executable, '-c',
            ('from pathlib import Path; from sb.restore_workspace import restore_workspace; '
            'import sys;\nwith restore_workspace(Path(sys.argv[1]), "b" * 64): pass'), str(folder)],
            capture_output=True, text=True, timeout=10, check=False)
        assert child.returncode != 0
        assert 'RESTORE_WORKSPACE_BUSY' in child.stderr
        assert original.read_text() == 'live restore source'
    assert not list(folder.iterdir())


def test_workspace_symlink_is_not_followed(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    (outside / 'keep').write_text('untouched')
    folder = tmp_path / 'restore'
    folder.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError), restore_workspace(folder, 'a' * 64):
        pytest.fail('must reject symlink')
    assert (outside / 'keep').read_text() == 'untouched'


def test_abandoned_name_symlink_does_not_delete_target(tmp_path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep').write_text('untouched')
    (folder / ('restore-' + 'a' * 64 + '-abcdefgh')).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match='RESTORE_WORKSPACE_UNSAFE'), restore_workspace(folder, 'b' * 64):
        pytest.fail('must reject symlink')
    assert (outside / 'keep').read_text() == 'untouched'


def test_unrecognized_entries_are_not_deleted(tmp_path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    (folder / 'notes').write_text('not restore material')
    with restore_workspace(folder, 'b' * 64) as staging:
        assert staging.is_dir()
    assert (folder / 'notes').read_text() == 'not restore material'
