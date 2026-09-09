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
        seed = """
from datetime import datetime, UTC
from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import GenerationMutation, GenerationAuthority, GenerationOperation
from sb.remember_page import materialize_remember
s = GenerationMutationService.from_config(load_config())
now = datetime.now(UTC)
try:
    s.mutate(GenerationMutation(mutation_id="installed:retained", operation=GenerationOperation.REMEMBER,
        now=now, authority=GenerationAuthority(None, None),
        apply=lambda root: materialize_remember(root, content="RetainedGamma maintenance memory",
            candidate_id="memcand:pos:v1:" + "c" * 64, created_at=now.isoformat(),
            release_sha="a" * 40)))
finally:
    s.close()
"""
        subprocess.run([str(python), '-I', '-c', seed], cwd=root, env=env, check=True, capture_output=True)
        snapshot_program = """
import hashlib,json
from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.search import SearchIndex
config=load_config()
s=GenerationMutationService.from_config(config)
try:
    active=s.store.active()
    hits=SearchIndex(active.root, registry_path=config.raw['knowledge_registry']).search('RetainedGamma', scope='reference')
    assert len(hits)==1
    page=active.root/(hits[0].page_id+'.md')
    assert 'RetainedGamma maintenance memory' in page.read_text()
    print(json.dumps({'generation':active.generation_id,
        'body_sha256':hashlib.sha256(page.read_bytes()).hexdigest(),
        'ledger_sha256':hashlib.sha256((active.root/'.sb/ledger.db').read_bytes()).hexdigest(),
        'high_water':s.requests.tombstone_high_water(), 'retrieved_records':len(hits)}))
finally:
    s.close()
"""

        def snapshot():
            done = subprocess.run([str(python), '-I', '-c', snapshot_program], cwd=root, env=env,
                                  check=True, capture_output=True, text=True, timeout=20)
            return json.loads(done.stdout)

        retained = snapshot()
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
            assert snapshot() == retained
            worker.kill()
            worker.wait(timeout=10)
            assert worker.returncode == -9
            cleaned = maintain()
            assert cleaned['disposed_restore_workspaces'] == 1 and not cleaned['restore_workspace_busy']
            assert not list(workspace.iterdir())
            assert snapshot() == retained
            repeated = maintain()
            assert repeated['disposed_restore_workspaces'] == 0
            assert snapshot() == retained
            print(json.dumps({'release': str(release), 'busy': busy, 'cleaned': cleaned,
                              'repeated': repeated, 'worker_exit': worker.returncode,
                              'retained_memory': retained, 'preservation_checks': 3}))
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)


if __name__ == '__main__':
    main()
