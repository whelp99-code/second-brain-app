"""Exercise explicit V4 migration against a real temporary request journal."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from sb.request_schema import migrate_scoped_v4
from sb.stable_requests import accept_stable_v3_request


def snapshot(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: db.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid').fetchall() for name in names}


def main():
    if sys.argv[1] == '--worker':
        with sqlite3.connect(sys.argv[2], isolation_level=None, timeout=30) as db:
            db.execute('PRAGMA foreign_keys=ON')
            print('ready', flush=True)
            assert sys.stdin.read(1) == 'x'
            migrate_scoped_v4(db)
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print('migrated', flush=True)
        return
    source = json.loads(Path(sys.argv[1]).read_text())['source_request']
    with tempfile.TemporaryDirectory(prefix='scoped-journal-') as folder:
        root = Path(folder) / 'requests'
        accepted = accept_stable_v3_request(root, source, datetime.fromisoformat(source['created_at']))
        journal = root / 'journal.db'
        pending = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'pending').iterdir()}
        with sqlite3.connect(journal) as db:
            before = snapshot(db)
            dependent = db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger','view') ORDER BY name").fetchall()
        workers = [subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(journal)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            for worker in workers:
                assert worker.stdout.readline().strip() == 'ready'
            for worker in workers:
                worker.stdin.write('x'); worker.stdin.flush()
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=30)
                assert worker.returncode == 0, stderr
                assert stdout.strip() == 'migrated'
            with sqlite3.connect(journal) as db:
                assert snapshot(db) == before
                assert db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger','view') ORDER BY name").fetchall() == dependent
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            assert pending == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'pending').iterdir()}
            print(json.dumps({'fixture': True, 'processes': 2, 'accepted_v3_request_id': accepted.request_id,
                'preserved_tables': len(before), 'preserved_dependencies': len(dependent),
                'preserved_pending_files': len(pending), 'foreign_key_errors': 0,
                'v4_runtime_enabled': False}, indent=2))
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill(); worker.wait()


if __name__ == '__main__':
    main()
