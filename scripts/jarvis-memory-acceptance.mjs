// Opt-in cross-repository acceptance. All writes go to fresh temporary fixtures.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {chmodSync, lstatSync, mkdtempSync, readdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const jarvis = resolve(process.argv[2] ?? join(sb, '../Orca-JARVIS'));
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
const load = path => import(pathToFileURL(join(jarvis, 'dist', path)).href);
const {outboxFixture, OUTBOX_NOW} = await load('tests/fixtures/memory-outbox-fixture.js');
const {closeMemoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
const {localKey} = await load('tests/helpers.js');
const {ControlPlane, signCommandApproval, MemoryOutboxService, createSecondBrainReadAdapter,
  createSecondBrainWriteRequestAdapter, createSecondBrainTransport} = await load('src/index.js');
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
const hash = value => createHash('sha256').update(value).digest('hex');
const root = mkdtempSync(join(tmpdir(), 'sb-jarvis-acceptance-'));
const releaseFixture = path => {
  if (!lstatSync(path).isDirectory()) return;
  chmodSync(path,0o700);
  for (const name of readdirSync(path)) releaseFixture(join(path,name));
};
const provider = mode => JSON.parse(execFileSync(python,
  ['-m', 'tests.fixtures.jarvis_memory_provider', mode, root], {cwd:sb,encoding:'utf8'}) || '{}');
let fixture;
let transport;
let secondTransport;
const initialCwd = process.cwd();
try {
  provider('init');
  const launcher = join(root, 'mcp');
  writeFileSync(launcher, `#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m tests.fixtures.jarvis_memory_provider serve ${quote(root)}\n`, {mode:0o700});
  process.chdir(jarvis);
  fixture = await outboxFixture();
  transport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const reader = createSecondBrainReadAdapter({transport,contract_profile:'schema4',clock:()=>OUTBOX_NOW,
    budgets:{max_hits:10,max_excerpt_bytes:4096,max_page_bytes:262144,max_total_bytes:65536},
    max_age_ms:86400000,expiry_ms:172800000});
  const writer = createSecondBrainWriteRequestAdapter(transport,fixture.database.authority,()=>OUTBOX_NOW);
  const content = fixture.request.payload.content;
  const contentHash = hash(content);
  const expected = {page_id:`wiki/memory-${hash(`${fixture.request.candidate_id}\0${contentHash}`)}`,
    sid:contentHash.slice(0,8),source_digest:`sha256:${contentHash}`};
  const control = new ControlPlane(fixture.database.authority);
  const previous = fixture.database.authority.db.prepare('SELECT args_json,target_json FROM control_command_requests WHERE request_id=?').get(fixture.commandId);
  const action = {schema_version:1,action:'memory.outbox.dispatch',action_level:3,
    request_id:'memory-real-provider',nonce:'memory-real-provider-nonce',reversible:false,
    requested_by:'principal:owner',requested_at:OUTBOX_NOW.toISOString(),
    expires_at:new Date(OUTBOX_NOW.getTime()+900000).toISOString(),target:JSON.parse(previous.target_json),
    args:{...JSON.parse(previous.args_json),expected_artifact:expected}};
  const staged = control.stage(action,OUTBOX_NOW);
  control.decide(signCommandApproval({schema_version:1,receipt_id:'memory-real-provider-receipt',
    request_id:action.request_id,decision:'approve',command_digest:staged.command_digest,
    signer_principal_id:'principal:owner',authenticated_session_id:'isolated-acceptance',key_id:'decision-test',
    algorithm:'Ed25519',issued_at:OUTBOX_NOW.toISOString(),not_before:OUTBOX_NOW.toISOString(),
    expires_at:action.expires_at,nonce:'memory-real-provider-receipt-nonce',max_uses:1,status:'issued'},
    localKey(fixture.database.authority)),OUTBOX_NOW);
  const service = new MemoryOutboxService({authority:fixture.database.authority,writer,reader,clock:()=>OUTBOX_NOW,
    candidate_dispatch_spool_root:join(fixture.database.root,'candidate-dispatch'),
    candidate_review_spool_root:join(fixture.database.root,'candidate-review')});
  const initial = await reader.search(content);
  const claimed = control.claim(action.request_id,'real-provider-worker',OUTBOX_NOW);
  const queued = service.enqueue(claimed);
  const dispatched = await service.runOnce('real-provider-worker',1);
  const accepted = await transport.call('sb_request_status',{request_id:fixture.request.request_id});
  const applied = provider('apply');
  const status = await transport.call('sb_request_status',{request_id:fixture.request.request_id});
  const reconciled = await service.reconcileOnce('real-provider-worker',1);
  const reused = await reader.search(content);
  const recent = await reader.recentChanges(1);
  secondTransport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const secondReader = createSecondBrainReadAdapter({transport:secondTransport,contract_profile:'schema4',clock:()=>OUTBOX_NOW,
    budgets:{max_hits:10,max_excerpt_bytes:4096,max_page_bytes:262144,max_total_bytes:65536},
    max_age_ms:86400000,expiry_ms:172800000});
  const shared = await secondReader.search(content);
  // Simulate a duplicate network delivery of exactly the already accepted envelope.
  const replay = await transport.call('sb_write_request',{request:fixture.request});
  const idle = provider('apply');
  const repeated = await service.runOnce('real-provider-worker',1);
  const terminalReplay = service.enqueue(claimed);
  const reviewFiles = readdirSync(join(fixture.database.root,'candidate-review'));
  const result = {initial:initial.kind,dispatched,accepted:accepted.value?.state,applied,
    provider_status:status.value?.state,reconciled,outbox:service.get(queued.outbox_id)?.state,
    reused:reused.kind,reuse_code:reused.code,evidence_count:reused.evidence?.length,
    recent:recent.kind,second_client:shared.kind,replayed:replay.value?.replayed,
    reapply:idle.state,redispatched:repeated.dispatched,terminal_replay:terminalReplay.state,
    remaining_review_files:reviewFiles.length,cleanup_error:reconciled.cleanup_error ?? null};
  console.log(JSON.stringify(result));
  assert.equal(result.accepted,'pending');
  assert.equal(result.provider_status,'proved');
  assert.equal(result.outbox,'settled');
  assert.equal(result.reused,'current');
  assert.equal(result.evidence_count,1);
  assert.equal(result.recent,'current');
  assert.equal(result.second_client,'current');
  assert.deepEqual(shared.evidence?.map(row=>row.record?.record_id),reused.evidence?.map(row=>row.record?.record_id));
  assert.equal(result.replayed,true);
  assert.equal(result.reapply,'idle');
  assert.equal(result.redispatched,0);
  assert.equal(result.terminal_replay,'settled');
  assert.equal(result.remaining_review_files,0);
  assert.equal(result.cleanup_error,null);
} finally {
  await transport?.close();
  await secondTransport?.close();
  if (fixture) closeMemoryDatabase(fixture.database);
  process.chdir(initialCwd);
  releaseFixture(root);
  rmSync(root,{recursive:true,force:true});
}
