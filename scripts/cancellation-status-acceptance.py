import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if len(sys.argv) > 1 and sys.argv[1] == 'reader':
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from sb.cancellation_status import read_cancellation_status
    from sb.effect_values import parse_instant
    value = json.load(sys.stdin)
    value['journal_path'] = Path(value['journal_path'])
    value['now'] = parse_instant(value['now'])
    for field in ('provider_keys', 'reader_keys'):
        value[field] = {key: Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw)) for key, raw in value[field].items()}
    value['revoked_provider_key_ids'] = frozenset(value.get('revoked_provider_key_ids', []))
    try:
        result = {'pid': os.getpid(), 'result': read_cancellation_status(**value)}
    except ValueError as exc:
        result = {'pid': os.getpid(), 'error': str(exc)}
    print(json.dumps(result))
    raise SystemExit()

from sb.effect_values import canonical_bytes, format_instant
from tests.test_cancellation_result import issue
from tests.test_cancellation_status import arguments
from tests.test_correction_cancellation_executor import prepare

work = Path(tempfile.mkdtemp(prefix='cancellation-status-acceptance-', dir='/var/tmp'))
executor, identity, _ = prepare(work)
expected = issue(executor, identity)
args = arguments(executor, identity)
before = list(executor.store.db.iterdump())
executor.close()
args['journal_path'] = str(args['journal_path'])
args['now'] = format_instant(args['now'])
for field in ('provider_keys', 'reader_keys'):
    args[field] = {key: public.public_bytes_raw().hex() for key, public in args[field].items()}

def read(value):
    process = subprocess.run([sys.executable, __file__, 'reader'], input=json.dumps(value),
        text=True, capture_output=True, cwd=ROOT, timeout=30, check=True)
    return json.loads(process.stdout)

first, second = read(args), read(args)
assert first['pid'] != second['pid'] != os.getpid()
assert canonical_bytes(first['result']['result']) == canonical_bytes(expected)
assert first['result'] == second['result']
revoked = read({**args, 'revoked_provider_key_ids': list(args['provider_keys'])})
assert revoked['error'] == 'MEMORY_CANCELLATION_RESULT_INVALID'
denied = read({**args, 'read_fence': None})
assert denied['error'] == 'TOMBSTONE_FENCE_REQUIRED'
import sqlite3

db = sqlite3.connect(Path(args['journal_path']).as_uri() + '?mode=ro', uri=True)
assert list(db.iterdump()) == before
db.close()
report = {'parent_pid': os.getpid(), 'reader_pids': [first['pid'], second['pid'], revoked['pid'], denied['pid']],
    'private_keys_in_reader_input': False, 'identical_replay': True, 'journal_rows_unchanged': True,
    'result_digest': expected['result_digest'], 'revoked': revoked['error'], 'unauthorized': denied['error'],
    'scope': 'real Python process, actual durable provider journal; no MCP/JARVIS cursor/operational deployment'}
(work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(work / 'result.json')
print(json.dumps(report))
