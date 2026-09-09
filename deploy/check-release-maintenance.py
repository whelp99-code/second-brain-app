"""Exercise installed restore maintenance against an isolated SIGKILL workspace."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    release = Path(sys.argv[1]).resolve(strict=True)
    python = release / '.venv/bin/python'
    with tempfile.TemporaryDirectory(prefix='sb-installed-maintenance-', dir='/var/tmp') as temporary:
        root = Path(temporary)
        config = root / 'config.toml'
        config.write_text('\n'.join(f'{key} = {json.dumps(str(root / value))}' for key, value in {
            'vault_root': 'share/vault', 'share_root': 'share', 'state_root': 'state',
            'request_root': 'requests', 'export_root': 'exports', 'backup_root': 'backups',
            'knowledge_registry': 'registry.sqlite',
        }.items()))
        env = {**os.environ, 'SB_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
        seed = ('from datetime import datetime,UTC; from sb.config import load_config; '
                'from sb.generation_runtime import GenerationMutationService; '
                's=GenerationMutationService.from_config(load_config()); '
                's.remember("installed maintenance fixture",None,datetime.now(UTC)); s.close()')
        subprocess.run([str(python), '-I', '-c', seed], cwd=root, env=env, check=True, capture_output=True)
        workspace = root / 'restore'
        workspace.mkdir(mode=0o700)
        program = ('from pathlib import Path; import sys; '
                   'from sb.restore_workspace import restore_workspace;\n'
                   'with restore_workspace(Path(sys.argv[1]), "a" * 64) as staging:\n'
                   ' (staging / "original").write_text("synthetic deleted original")\n'
                   ' print("ready",flush=True)\n'
                   ' sys.stdin.read(1)\n')
        worker = subprocess.Popen([str(python), '-I', '-c', program, str(workspace)],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        command = [str(release / 'bin/sb'), 'maintain', '--once', '--restore-workspace', str(workspace)]

        def maintain():
            done = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                                  timeout=20, check=True)
            return json.loads(done.stdout)

        try:
            import selectors
            with selectors.DefaultSelector() as selector:
                selector.register(worker.stdout, selectors.EVENT_READ)
                assert selector.select(20), 'installed worker readiness timeout'
            assert worker.stdout is not None and worker.stdout.readline().strip() == 'ready'
            busy = maintain()
            assert busy['restore_workspace_busy'] is True
            assert len(list(workspace.rglob('original'))) == 1
            worker.kill()
            worker.wait(timeout=10)
            assert worker.returncode == -9
            cleaned = maintain()
            assert cleaned['disposed_restore_workspaces'] == 1 and not cleaned['restore_workspace_busy']
            assert not list(workspace.iterdir())
            repeated = maintain()
            assert repeated['disposed_restore_workspaces'] == 0
            print(json.dumps({'release': str(release), 'busy': busy, 'cleaned': cleaned,
                              'repeated': repeated, 'worker_exit': worker.returncode}))
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)


if __name__ == '__main__':
    main()
