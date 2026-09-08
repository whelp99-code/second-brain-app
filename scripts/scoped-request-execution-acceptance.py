"""Independent admission/executor/read processes with explicit fixture authority."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.scoped_request_acceptance import accept_scoped_request
from tests.task30_process_harness import executor_config


def worker():
    mode, root, fixture = sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    raw = json.loads(fixture.read_text())
    now = datetime.fromisoformat(raw['created_at'])
    config = executor_config(root)
    if mode == 'accept':
        value = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
            clock=lambda: now, validate_authority=lambda _: True)
        print(json.dumps(asdict(value)))
        return
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    try:
        result = executor.apply_once(worker='fixture:worker', now=now)
        status = executor.store.get(raw['request_id'])
        receipt = json.loads((config.request_root / 'receipts' / f"{raw['request_id']}.json").read_text())
        print(json.dumps({'apply': asdict(result), 'generation_root': str(executor.generations.active().root),
            'receipt': receipt, 'proof': json.loads(status.proof_json)}))
    finally:
        executor.close()


def main():
    if sys.argv[1] == '--worker':
        worker()
        return
    fixture = Path(sys.argv[1]).resolve()
    temporary = Path(tempfile.mkdtemp(prefix='scoped-execution-'))
    def call(mode):
        return json.loads(subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
            '--worker', mode, str(temporary), str(fixture)], text=True, timeout=60))
    try:
        accepted = call('accept')
        executed = call('execute')
        assert executed['apply']['state'] == 'proved'
        assert executed['receipt']['schema_version'] == 4 and executed['receipt']['state'] == 'proved'
        assert executed['proof']['request_id'] == accepted['request_id']
        assert executed['proof']['request_digest'] == accepted['request_digest']
        assert executed['proof']['scope_digest'] == accepted['scope_digest']
        reads = [json.loads(subprocess.check_output([sys.executable,
            'scripts/scoped-remember-materialization-acceptance.py', '--read', executed['generation_root'], project],
            text=True, timeout=30)) for project in ['project:shared-memory', 'project:shared-memory', 'project:other']]
        assert reads[0] == reads[1] and reads[0]['records'] == 4
        assert reads[2] == {'denied': 'MEMORY_ACCESS_DENIED'}
        replay = call('accept')
        assert replay['replayed'] and replay['request_file_digest'] == accepted['request_file_digest']
        assert call('execute')['apply']['state'] == 'idle'
        assert not list((temporary / 'requests/pending').glob('*.json'))
        print(json.dumps({'fixture_authority': True, 'processes': 7, 'accepted': accepted,
            'provider_result': executed['apply'], 'receipt': executed['receipt'], 'proof': executed['proof'],
            'reads': reads, 'replayed': True, 'redispatch_idle': True, 'pending_files': 0,
            'mcp_write_completed': False}, indent=2))
    finally:
        for root, dirs, files in os.walk(temporary):
            os.chmod(root, 0o700)
            for name in dirs:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o700)
            for name in files:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o600)
        shutil.rmtree(temporary)


if __name__ == '__main__':
    main()
