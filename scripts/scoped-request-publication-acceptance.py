"""Crash/restart the actual publisher in isolated processes and private folders."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sb.scoped_request_publication import publish_scoped_pending


def worker():
    value = json.loads(Path(sys.argv[3]).read_text())
    at = datetime.fromisoformat(value['created_at'])
    barrier = sys.argv[4]
    class ExitAtBarrier:
        def reach(self, event):
            if event.barrier_id.value == barrier:
                os._exit(73)
    if barrier == 'resume':
        at += timedelta(milliseconds=1)
    result = publish_scoped_pending(Path(sys.argv[2]), value, now=at,
        expected_provider='provider:fixture', barrier_sink=ExitAtBarrier())
    print(json.dumps({'accepted_at': result.accepted_at, 'file_digest': result.file_digest,
        'bytes_sha256': hashlib.sha256(result.canonical).hexdigest()}))


def main():
    if sys.argv[1] == '--worker':
        worker()
        return
    fixture = Path(sys.argv[1]).resolve()
    results = []
    for barrier in ('request_temp_write', 'pending_publish_fsync'):
        with tempfile.TemporaryDirectory(prefix='scoped-publish-crash-') as root:
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', root, str(fixture)]
            crashed = subprocess.run([*command, barrier], capture_output=True, text=True, timeout=30, check=False)
            assert crashed.returncode == 73, crashed.stderr
            prior = next(Path(root).iterdir()).read_bytes()
            resumed = json.loads(subprocess.check_output([*command, 'resume'], text=True, timeout=30))
            files = list(Path(root).iterdir())
            assert len(files) == 1 and files[0].name.endswith('.v4.json')
            assert files[0].read_bytes() == prior
            assert resumed['bytes_sha256'] == hashlib.sha256(prior).hexdigest()
            assert resumed['accepted_at'] == json.loads(prior)['accepted_at']
            results.append({'barrier': barrier, 'exit_code': 73, 'original_bytes_preserved': True,
                'original_timestamp_preserved': True, 'remaining_files': 1, **resumed})
    print(json.dumps({'fixture': True, 'processes': 4, 'results': results,
                     'provider_acceptance_completed': False, 'journal_rows_created': 0}, indent=2))


if __name__ == '__main__':
    main()
