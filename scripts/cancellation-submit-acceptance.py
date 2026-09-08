"""Real JARVIS DB intent -> Node transport -> Python MCP admission and lost response recovery."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sb.effect_values import canonical_bytes
from sb.mcp_contract import write_fixture_request
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request
from tests.test_correction_cancellation import HISTORICAL
from tests.test_request_executor import _config

if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] not in ('--record-result', '--compact-result', '--rebuild-result', '--swap-result', '--settle-result', '--dispatch-result')):
    raise SystemExit('usage: python scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD [--record-result|--compact-result|--rebuild-result|--swap-result|--settle-result|--dispatch-result]')
record_result = len(sys.argv) == 3
compact_result = record_result and sys.argv[2] in ("--compact-result", "--rebuild-result", "--swap-result", "--settle-result", "--dispatch-result")
rebuild_result = record_result and sys.argv[2] == "--rebuild-result"
swap_result = record_result and sys.argv[2] == "--swap-result"
settle_result = record_result and sys.argv[2] in ("--settle-result", "--dispatch-result")
work = Path(tempfile.mkdtemp(prefix='cancellation-submit-acceptance-', dir='/var/tmp'))
c = _config(work)
seed = write_fixture_request()
seed.pop('request_id'); seed.pop('request_digest')
seed['created_at'] = seed['receipt']['issued_at'] = '2026-08-28T00:00:00.000Z'
seed['expires_at'] = seed['receipt']['expires_at'] = '2026-08-29T00:00:00.000Z'
digest = lambda domain, value: 'sha256:' + hashlib.sha256(domain + canonical_bytes(value)).hexdigest()
seed['receipt_digest'] = digest(b'orca-jarvis/memory-write-receipt/v1\0', seed['receipt'])
seed['request_digest'] = digest(b'orca-jarvis/memory-write-request/v1\0', seed)
seed['request_id'] = 'memreq:pos:v1:' + seed['request_digest'][7:]
seed_time = datetime(2026, 8, 28, 11, 59, tzinfo=UTC)
accept_stable_v1_request(c.request_root, seed, seed_time)
executor = RequestExecutor(c)
try:
    assert executor.apply_once(now=seed_time).state == 'proved'
    generation = executor.generations.active()
    original = effect_request(generation, 'correct', 'ExampleAlpha 예시기록',
        datetime(2026, 8, 28, 12, tzinfo=UTC), executor.store.tombstone_high_water(), HISTORICAL, '1')
    public = base64.urlsafe_b64encode(HISTORICAL.public_key().public_bytes_raw()).decode().rstrip('=')
    config = work / 'config.toml'
    config.write_text('\n'.join([
        f'vault_root = "{c.share_root / "vault"}"', f'request_root = "{c.request_root}"',
        f'state_root = "{c.state_root}"', f'share_root = "{c.share_root}"', f'export_root = "{c.export_root}"',
        f'backup_root = "{c.backup_root}"', 'provider_instance_id = "provider:fixture"',
        f'provider_release_sha = "{c.provider_release_sha}"', 'revoked_jarvis_signing_key_ids = []',
        '[jarvis_public_keys]', f'"jarvis:fixture" = "{public}"',
        '[cancellation_public_keys]', f'"jarvis:fixture" = "{public}"',
    ])+'\n')
    flag = work / 'crash-after-commit'; flag.touch()
    launcher = work / 'second-brain-mcp'
    launcher.write_text(f'''#!{sys.executable}
import os, sys
from pathlib import Path
from datetime import datetime, UTC
sys.path.insert(0, {str(ROOT)!r})
import sb.mcp as module
class Clock:
    @classmethod
    def now(cls, tz=None): return datetime(2026,8,28,12,0,1,tzinfo=UTC)
module.datetime = Clock
submit = module.submit_correction_cancellation
def crash_after_commit(*args, **kwargs):
    result = submit(*args, **kwargs)
    flag = Path({str(flag)!r})
    if flag.exists():
        flag.unlink()
        os._exit(77)
    return result
module.submit_correction_cancellation = crash_after_commit
module.main()
''')
    launcher.chmod(0o700)
    execution_config = work / 'execution-config.toml'
    if record_result:
        private = base64.urlsafe_b64encode(HISTORICAL.private_bytes_raw()).decode().rstrip('=')
        execution_config.write_text('provider_signing_key_id = "provider:key"\nprovider_private_key = "'+private+'"\n'+config.read_text())
        execution_config.chmod(0o600)
    payload = {'dispatch_result': record_result and sys.argv[2] == '--dispatch-result', 'work': str(work), 'settle_result': settle_result, 'swap_result': swap_result, 'rebuild_result': rebuild_result, 'compact_result': compact_result, 'record_result': record_result, 'execution_config': str(execution_config),
        'python': sys.executable, 'sb_root': str(ROOT), 'build': str(Path(sys.argv[1]).resolve()), 'launcher': str(launcher), 'config': str(config),
        'contract': str(ROOT / 'contracts/second-brain-mcp-v5.json'),
        'resolved': {'target': original['targets'][0], 'scope': original['scope']}}
    run = subprocess.run(['node', str(ROOT / 'scripts/cancellation-submit-acceptance.mjs')],
        input=json.dumps(payload), text=True, capture_output=True, timeout=120, cwd=ROOT.parent / "Orca-JARVIS")
    if run.returncode:
        print(run.stderr, file=sys.stderr)
        raise SystemExit(run.returncode)
    observed = json.loads(run.stdout)
    assert (executor.generations.active().generation_id == generation.generation_id) is (not record_result)
    assert executor.store.db.execute('SELECT count(*) FROM correction_cancellations').fetchone()[0] == 1
    assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_aliases').fetchone()[0] == 8
    assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == int(record_result)
    assert executor.store.tombstone_high_water()[0] == (2 if payload['dispatch_result'] else 1)
    report = {**observed, 'python_parent_pid': os.getpid(), 'accepted_rows': 1, 'alias_rows': 8,
        'result_rows': int(record_result), 'generation_unchanged': not record_result, 'provider_tombstone_sequence': executor.store.tombstone_high_water()[0],
        'private_key_in_mcp_config': False, 'clock': 'cancellation admission fixed 2026-08-28; execution and followup actual UTC',
        'scope': ('actual JARVIS seq2 MCP dispatch, provider proof and observations, local compaction and settled; separate-process exact replay' if payload['dispatch_result'] else 'actual provider cancellation, local compaction and atomic settlement; cursor advanced to 1' if settle_result else 'actual provider execution and JARVIS durable result reception; cursor not advanced' if record_result else 'actual JARVIS SQLite issuer and Node transport to actual Python provider target admission; execution/cursor settlement not performed')}
    (work / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(work / 'result.json')
    print(json.dumps(report))
finally:
    executor.close()
