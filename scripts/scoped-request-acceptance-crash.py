"""Internal admission crash/retry with fixture authority, never production MCP."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from sb.scoped_request_acceptance import accept_scoped_request


def worker():
    raw = json.loads(Path(sys.argv[3]).read_text())
    now = datetime.fromisoformat(raw['created_at'])
    mode = sys.argv[4]
    class Stop:
        def reach(self, event):
            if mode == 'file' and event.barrier_id.value == 'pending_publish_fsync':
                os._exit(73)
    result = accept_scoped_request(Path(sys.argv[2]), raw, expected_provider='provider:fixture',
        clock=lambda: now + timedelta(milliseconds=1 if mode == 'retry' else 0),
        validate_authority=lambda _request: True, barrier_sink=Stop())
    if mode == 'commit':
        os._exit(74)
    print(json.dumps(asdict(result)))


def main():
    if sys.argv[1] == '--worker':
        worker()
        return
    fixture = Path(sys.argv[1]).resolve()
    results = []
    for mode, code in [('file', 73), ('commit', 74)]:
        with tempfile.TemporaryDirectory(prefix='scoped-admission-crash-') as folder:
            root = Path(folder) / 'requests'
            args = [sys.executable, str(Path(__file__).resolve()), '--worker', str(root), str(fixture)]
            crashed = subprocess.run([*args, mode], capture_output=True, text=True, timeout=30, check=False)
            assert crashed.returncode == code, crashed.stderr
            file = next((root / 'pending').glob('*.json'))
            original = file.read_bytes()
            with sqlite3.connect(root / 'journal.db') as db:
                before = db.execute('SELECT count(*) FROM requests').fetchone()[0]
            assert before == (1 if mode == 'commit' else 0)
            retry = json.loads(subprocess.check_output([*args, 'retry'], text=True, timeout=30))
            assert retry['replayed'] == (mode == 'commit')
            assert retry['accepted_at'] == json.loads(original)['accepted_at']
            assert file.read_bytes() == original
            with sqlite3.connect(root / 'journal.db') as db:
                assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 1
                assert db.execute('SELECT state FROM requests').fetchone()[0] == 'pending'
            results.append({'crash': mode, 'exit_code': code, 'rows_before_retry': before,
                'rows_after_retry': 1, 'original_file_preserved': True,
                'bytes_sha256': hashlib.sha256(original).hexdigest(), 'acceptance': retry})
    print(json.dumps({'fixture_authority': True, 'processes': 4, 'results': results,
                     'mcp_write_completed': False, 'provider_execution_completed': False}, indent=2))


if __name__ == '__main__':
    main()
