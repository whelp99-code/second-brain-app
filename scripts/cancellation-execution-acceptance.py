"""Actual submit -> CLI interruption/recovery -> private-key-free MCP result verification."""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import serialization
from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_values import model_object
from sb.erasure import scan_managed_surfaces
from tests.test_correction_cancellation import HISTORICAL

if len(sys.argv) != 2:
    raise SystemExit('usage: python scripts/cancellation-execution-acceptance.py ISOLATED_JARVIS_BUILD')
build = str(Path(sys.argv[1]).resolve())
reports = []
for phase in ('predecessor_disposal', 'cancellation_result_committed'):
    submitted = subprocess.run([sys.executable, str(ROOT / 'scripts/cancellation-submit-acceptance.py'), build],
        text=True, capture_output=True, cwd=ROOT, check=True, timeout=90)
    submission = Path(submitted.stdout.splitlines()[0])
    work = submission.parent
    initial = json.loads(submission.read_text())
    identity = initial['intent_id']
    config = work / 'execution-config.toml'
    public = base64.urlsafe_b64encode(HISTORICAL.public_key().public_bytes_raw()).decode().rstrip('=')
    private = base64.urlsafe_b64encode(HISTORICAL.private_bytes_raw()).decode().rstrip('=')
    base = (work / 'config.toml').read_text().replace('revoked_jarvis_signing_key_ids = ["jarvis:fixture"]', 'revoked_jarvis_signing_key_ids = []')
    config.write_text('provider_signing_key_id = "provider:key"\nprovider_private_key = "'+private+'"\n'+base)
    config.chmod(0o600)
    crash = work / 'crash-execution.py'
    crash.write_text(f'''import os, sys
sys.path.insert(0, {str(ROOT)!r})
import sb.cli_cancellation as boundary
from sb.cli import main
execute = boundary.execute_cancellation
def interrupted(*args, **kwargs):
    def barrier(phase):
        if phase == {phase!r}: os._exit(77)
    return execute(*args, **kwargs, barrier=barrier)
boundary.execute_cancellation = interrupted
raise SystemExit(main(["apply-cancellation", "--intent-id", {identity!r}]))
''')
    env = {**os.environ, 'SB_CONFIG': str(config), 'TMPDIR': '/var/tmp'}
    stopped = subprocess.run([sys.executable, str(crash)], env=env, cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert stopped.returncode == 77, (stopped.returncode, stopped.stderr)
    def execute():
        completed = subprocess.run([sys.executable, '-m', 'sb.cli', 'apply-cancellation', '--intent-id', identity],
            env=env, cwd=ROOT, text=True, capture_output=True, timeout=60, check=True)
        return json.loads(completed.stdout)
    result = execute()
    assert result['state'] == 'provider_local_suppressed'
    assert execute() == result
    journal = sqlite3.connect(work / 'requests/journal.db')
    try:
        intent = json.loads(journal.execute('SELECT intent_json FROM correction_cancellations WHERE intent_id=?', (identity,)).fetchone()[0])
        assert journal.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == 1
    finally:
        journal.close()
    # Scan the actual generation directory: the public entry is an intentional symlink.
    scan = scan_managed_surfaces(((work / 'share/vault').resolve(),), ('ExampleAlpha 예시기록'.encode(), b'Corrected fixture memory.'))
    assert scan.matches == 0 and scan.scan_errors == 0
    reader = work / 'reader-config.toml'
    reader.write_text(base+'\n[provider_result_public_keys]\n"provider:key" = "'+public+'"\n')
    assert 'provider_private_key' not in reader.read_text()
    launcher = work / 'reader-mcp'
    launcher.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom sb.mcp import main\nmain()\n')
    launcher.chmod(0o700)
    now = datetime.now(UTC)
    fence = model_object(create_read_fence(provider_instance_id='provider:fixture', purpose='memory_status', operation='status',
        sequence=result['tombstone_sequence'], set_root=result['tombstone_set_root'], issued_at=format_instant(now),
        not_before=format_instant(now), expires_at=format_instant(now+timedelta(minutes=5)), nonce='cli-execution-status-'+phase,
        signing_key_id='jarvis:fixture', private_key=HISTORICAL))
    payload = {'build': build, 'launcher': str(launcher), 'config': str(reader),
        'contract': str(ROOT / 'contracts/second-brain-mcp-v4.json'), 'intent': intent, 'fence': fence,
        'key_id': 'provider:key', 'public_key': HISTORICAL.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        'expected_state': 'provider_local_suppressed', 'expected_result': result}
    checked = subprocess.run(['node', str(ROOT / 'scripts/cancellation-mcp-acceptance.mjs')], input=json.dumps(payload),
        cwd=ROOT, text=True, capture_output=True, timeout=60, check=True)
    reports.append({'phase': phase, 'exit_code': stopped.returncode, 'submission': str(submission),
        'result_digest': result['result_digest'], 'identical_cli_replay': True, 'body_matches': scan.matches,
        'scan_errors': scan.scan_errors, 'result_rows': 1, 'mcp': json.loads(checked.stdout)})
report = {'reports': reports, 'scope': 'actual JARVIS DB submission, explicit Python CLI execution and Node MCP verification in isolated fixtures; no JARVIS cursor settlement or operational deployment'}
path = Path(tempfile.mkdtemp(prefix='cancellation-execution-acceptance-', dir='/var/tmp')) / 'result.json'
path.write_text(json.dumps(report, indent=2)+'\n')
print(path)
print(json.dumps(report))
