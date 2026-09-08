// Actual Node producer -> Python journal boundary -> fresh-process replay tests in synthetic roots.
import assert from 'node:assert/strict';
import {createPrivateKey, createPublicKey} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const [buildArgument] = process.argv.slice(2);
assert(buildArgument?.startsWith('/'));
const build = resolve(buildArgument), sb = process.cwd();
process.umask(0o077);
const root = mkdtempSync('/var/tmp/cancellation-journal-cross-runtime-');
const {createCorrectionCancellationIntent} = await import(pathToFileURL(
  join(build, 'dist/src/memory-correction-cancellation-intent.js')));
const key = start => createPrivateKey({key: Buffer.concat([
  Buffer.from('302e020100300506032b657004220420', 'hex'),
  Buffer.from(Array.from({length: 32}, (_, i) => start + i)),
]), format: 'der', type: 'pkcs8'});
const historical = key(0), current = key(32), stamp = '2026-08-31T00:01:02.000Z';
const bootstrap = String.raw`
import json,sys,os
from pathlib import Path
from tests.test_correction_cancellation_executor import prepare_unaccepted
root=Path(sys.argv[1]); originals=[]
for name in ('cancel-first','original-first','wrong-target'):
 executor,intent,original=prepare_unaccepted(root/name)
 originals.append(original);executor.close()
assert originals[0]==originals[1]==originals[2]
print(json.dumps(dict(pid=os.getpid(),original=originals[0])))
`;
const initialized = spawnSync(join(sb, '.venv/bin/python'), ['-c', bootstrap, root], {
  cwd: sb, encoding: 'utf8', timeout: 30_000, env: {...process.env, TMPDIR: '/var/tmp'},
});
assert.equal(initialized.status, 0, initialized.stderr);
const prepared = JSON.parse(initialized.stdout);
const original = prepared.original;
const intent = createCorrectionCancellationIntent(original, {
  candidate_id: 'memcand:pos:v1:' + 'a'.repeat(64), suppression_event_digest: 'sha256:' + 'b'.repeat(64),
  dispatch_fence: 0, attempt_count: 0, active_cursor: false,
}, {issued_at: stamp, expires_at: '2026-08-31T00:06:02.000Z', nonce: 'journal-interop', signing_key_id: 'jarvis:current'},
current, {provider_instance_id: 'provider:fixture', now: new Date(stamp),
  historical_delegation_keys: new Map([['jarvis:fixture', createPublicKey(historical)]]),
  current_cancellation_keys: new Map([['jarvis:current', createPublicKey(current)]])});
assert.equal('payload' in intent, false);
writeFileSync(join(root, 'intent.json'), JSON.stringify(intent));
writeFileSync(join(root, 'original.json'), JSON.stringify(original));
const frozenOriginal = JSON.parse(readFileSync(join(build, 'contracts/second-brain-mcp-v1.json'), 'utf8')).vectors.correction.request;
const wrongTarget = createCorrectionCancellationIntent(frozenOriginal, intent.unsent_evidence,
  {issued_at: stamp, expires_at: '2026-08-31T00:06:02.000Z', nonce: 'wrong-target', signing_key_id: 'jarvis:current'},
  current, {provider_instance_id: 'provider:fixture', now: new Date(stamp),
    historical_delegation_keys: new Map([['jarvis:fixture', createPublicKey(historical)]]),
    current_cancellation_keys: new Map([['jarvis:current', createPublicKey(current)]])});
writeFileSync(join(root, 'wrong-target-intent.json'), JSON.stringify(wrongTarget));
const script = String.raw`
import json,os,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.effect_values import parse_instant
from sb.effect_write_requests import accept_effect_request
from sb.request_executor import RequestExecutor
from tests.test_request_executor import _config
root=Path(sys.argv[1]); provider=root/sys.argv[2]; mode=sys.argv[3]
executor=RequestExecutor(_config(provider));journal=executor.config.request_root
now=parse_instant('2026-08-31T00:01:02.000Z')
historical=Ed25519PrivateKey.from_private_bytes(bytes(range(32))).public_key()
current=Ed25519PrivateKey.from_private_bytes(bytes(range(32,64))).public_key()
try:
 if mode in ('cancel','wrong-target'):
  filename='wrong-target-intent.json' if mode=='wrong-target' else 'intent.json'
  result,replayed=accept_correction_cancellation(journal,json.loads((root/filename).read_text()),
   generations=executor.generations,clock=lambda:now,
   expected_provider='provider:fixture',historical_delegation_keys={'jarvis:fixture':historical},
   current_cancellation_keys={'jarvis:current':current})
  state=result['state']
 else:
  result=accept_effect_request(journal,json.loads((root/'original.json').read_text()),now,
   public_keys={'jarvis:fixture':historical},provider_instance_id='provider:fixture')
  state=result.state;replayed=result.replayed
except (ValueError,RuntimeError) as exc:
 state=str(exc);replayed=False
store=executor.store
try:
 aliases=store.db.execute('SELECT count(*) FROM correction_cancellation_aliases').fetchone()[0]
 requests=store.db.execute('SELECT count(*) FROM requests').fetchone()[0]
 sequence=store.verified_tombstone_snapshot().sequence
finally:executor.close()
print(json.dumps(dict(pid=os.getpid(),mode=mode,state=state,replayed=replayed,aliases=aliases,
 requests=requests,sequence=sequence,pending_files=len(list((journal/'pending').iterdir())))))
`;
function run(journal, mode) {
  const child = spawnSync(join(sb, '.venv/bin/python'), ['-c', script, root, journal, mode], {
    cwd: sb, encoding: 'utf8', timeout: 30_000, env: {...process.env, TMPDIR: '/var/tmp'},
  });
  assert.equal(child.status, 0, child.stderr || String(child.error));
  return JSON.parse(child.stdout);
}
const accepted = run('cancel-first', 'cancel');
assert.equal(accepted.state, 'suppression_pending'); assert.equal(accepted.aliases, 8);
assert.equal(accepted.sequence, 1); assert.equal(accepted.requests, 1); assert.equal(accepted.pending_files, 0);
const blocked = run('cancel-first', 'original');
assert.equal(blocked.state, 'MEMORY_REQUEST_CANCELLED'); assert.equal(blocked.pending_files, 0);
const replay = run('cancel-first', 'cancel'); assert.equal(replay.replayed, true);
const received = run('original-first', 'original'); assert.equal(received.state, 'pending');
const rejected = run('original-first', 'cancel');
assert.equal(rejected.state, 'MEMORY_CANCELLATION_ALREADY_RECEIVED');
assert.equal(rejected.aliases, 0); assert.equal(rejected.requests, 2); assert.equal(rejected.pending_files, 1);
const wrong = run('wrong-target', 'wrong-target');
assert.equal(wrong.state, 'EFFECT_PRIOR_STALE'); assert.equal(wrong.aliases, 0);
assert.equal(wrong.sequence, 0); assert.equal(wrong.requests, 1); assert.equal(wrong.pending_files, 0);
const results = [accepted, blocked, replay, received, rejected, wrong];
assert.equal(new Set(results.map(item => item.pid)).size, 6);
const report = {root, build, node_pid: process.pid, bootstrap_pid: prepared.pid, actual_target_binding: true, intent_digest: intent.intent_digest, results,
  operational_mutations: 0, mcp_route_exercised: false, generation_proof: false, automatic_recovery: false};
writeFileSync(join(root, 'result.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
