from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sb.restore_workspace import restore_workspace
from tests.json_fixtures import parse_object


def test_live_restore_is_protected_from_another_process(tmp_path: Path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    with restore_workspace(folder, 'a' * 64) as staging:
        original = staging / 'original'
        _ = original.write_text('live restore source')
        child = subprocess.run([sys.executable, '-c',
            ('from pathlib import Path; from sb.restore_workspace import restore_workspace; '
            'import sys;\nwith restore_workspace(Path(sys.argv[1]), "b" * 64): pass'), str(folder)],
            capture_output=True, text=True, timeout=10, check=False)
        assert child.returncode != 0
        assert 'RESTORE_WORKSPACE_BUSY' in child.stderr
        assert original.read_text() == 'live restore source'
    assert not list(folder.iterdir())


def test_workspace_symlink_is_not_followed(tmp_path: Path):
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    _ = (outside / 'keep').write_text('untouched')
    folder = tmp_path / 'restore'
    folder.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError), restore_workspace(folder, 'a' * 64):
        pytest.fail('must reject symlink')
    assert (outside / 'keep').read_text() == 'untouched'


def test_abandoned_name_symlink_does_not_delete_target(tmp_path: Path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    outside = tmp_path / 'outside'
    outside.mkdir()
    _ = (outside / 'keep').write_text('untouched')
    (folder / ('restore-' + 'a' * 64 + '-abcdefgh')).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match='RESTORE_WORKSPACE_UNSAFE'), restore_workspace(folder, 'b' * 64):
        pytest.fail('must reject symlink')
    assert (outside / 'keep').read_text() == 'untouched'


def test_unrecognized_entries_are_not_deleted(tmp_path: Path):
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    _ = (folder / 'notes').write_text('not restore material')
    with restore_workspace(folder, 'b' * 64) as staging:
        assert staging.is_dir()
    assert (folder / 'notes').read_text() == 'not restore material'


def test_maintenance_cli_skips_live_workspace_then_cleans_abandoned(tmp_path: Path):
    import json
    import os
    from datetime import UTC, datetime

    from sb.generation_runtime import GenerationMutationService
    from tests.test_runtime_reliability import managed

    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember('maintenance retained memory', None, datetime.now(UTC))
    finally:
        service.close()
    config_path = tmp_path / 'config.toml'
    _ = config_path.write_text('\n'.join(f'{key} = {json.dumps(value)}'
                                    for key, value in config.raw.items() if isinstance(value, str)))
    env = {**os.environ, 'SB_CONFIG': str(config_path)}
    folder = tmp_path / 'restore'
    folder.mkdir(mode=0o700)
    command = [sys.executable, '-c', 'from sb.cli import main; raise SystemExit(main())',
               'maintain', '--once', '--restore-workspace', str(folder)]
    with restore_workspace(folder, 'a' * 64) as staging:
        _ = (staging / 'live').write_text('keep')
        done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20, check=False)
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)['restore_workspace_busy'] is True
        assert (staging / 'live').read_text() == 'keep'
    worker = subprocess.run([sys.executable, '-c',
        ('from pathlib import Path; import os,signal,sys; '
         'from sb.restore_workspace import restore_workspace;\n'
         'with restore_workspace(Path(sys.argv[1]), "b" * 64) as staging:\n'
         ' (staging / "deleted-source").write_text("forgotten original")\n'
         ' os.kill(os.getpid(), signal.SIGKILL)'), str(folder)],
        capture_output=True, text=True, timeout=10, check=False)
    assert worker.returncode == -9
    assert list(folder.iterdir())
    done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20, check=False)
    assert done.returncode == 0, done.stderr
    result = parse_object(done.stdout)
    assert result['disposed_restore_workspaces'] == 1
    assert result['restore_workspace_busy'] is False
    assert not list(folder.iterdir())
    again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20, check=False)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)['disposed_restore_workspaces'] == 0
