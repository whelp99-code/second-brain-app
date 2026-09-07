// Opt-in cross-repository acceptance. All writes go to fresh temporary fixtures.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {chmodSync, lstatSync, mkdtempSync, readdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ownerMemoryFixture} from './jarvis-owner-memory-fixture.mjs';
import {prepareReadFenceDeletion} from './jarvis-read-fence-fixture.mjs';
import {pausedCompile} from './jarvis-compile-fixture.mjs';

const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const jarvis = resolve(process.argv[2] ?? join(sb, '../Orca-JARVIS'));
const ownerConfirmed = process.argv.includes('--owner-confirmed');
const approvalRollback = process.argv.includes('--approval-rollback');
const runtimeCli = process.argv.includes('--runtime-cli');
const afterDelete = process.argv.includes('--after-delete');
const duringCompile = process.argv.includes('--during-compile');
if (duringCompile && !runtimeCli) throw new Error('--during-compile requires --runtime-cli');
if (afterDelete && !runtimeCli) throw new Error('--after-delete requires --runtime-cli');
if (runtimeCli && !ownerConfirmed) throw new Error('--runtime-cli requires --owner-confirmed');
if (approvalRollback && !ownerConfirmed) throw new Error('--approval-rollback requires --owner-confirmed');
const recordSet = process.argv.includes('--record-set');
const recordLimit = process.argv.includes('--record-limit');
const recordBudget = process.argv.includes('--record-budget');
const sensitive = process.argv.includes('--sensitive');
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
const load = path => import(pathToFileURL(join(jarvis, 'dist', path)).href);
const {outboxFixture, OUTBOX_NOW} = await load('tests/fixtures/memory-outbox-fixture.js');
const {closeMemoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
const {localKey} = await load('tests/helpers.js');
const {execute} = await load('src/cli-runtime.mjs');
const {MemoryOutboxRecordReader} = await load('src/memory-outbox-record.js');
const {createProductionMemoryReadFence} = await load('src/memory-read-fence-production.js');
const {ControlPlane, signCommandApproval, MemoryOutboxService, createSecondBrainReadAdapter,
  createSecondBrainWriteRequestAdapter, createSecondBrainTransport, memoryRememberArtifact,
  prepareMemoryRememberDispatch} = await load('src/index.js');
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
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
let compiler;
const initialCwd = process.cwd();
try {
  provider('init');
  const launcher = join(root, 'mcp');
  writeFileSync(launcher, `#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m tests.fixtures.jarvis_memory_provider serve ${quote(root)}\n`, {mode:0o700});
  process.chdir(jarvis);
  fixture = ownerConfirmed ? await ownerMemoryFixture(load,OUTBOX_NOW, {
    ...(recordSet ? {statement:'공통 기억 첫째\u2028  반복 기억  \u0085\u0085반복 기억\u2029사용자 [^deadbeef] 기록'} : {}),
    ...(recordLimit ? {statement:Array(64).fill('a'.repeat(60)).join('\u2028')} : {}),
    ...(sensitive ? {sensitivity:'sensitive'} : {}),
  }, approvalRollback) : await outboxFixture();
  transport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const deleted = afterDelete ? await prepareReadFenceDeletion({load,fixture,transport,provider,now:OUTBOX_NOW}) : undefined;
  const readFence = afterDelete ? createProductionMemoryReadFence(fixture.database.authority) : undefined;
  const budgetProfile = recordBudget ? 'record-set-v1' : 'interactive';
  const readBudgets = {max_hits:10,max_excerpt_bytes:4096,max_page_bytes:262144,max_total_bytes:recordBudget ? 262144 : 65536};
  const reader = createSecondBrainReadAdapter({transport,contract_profile:'schema4',budget_profile:budgetProfile,clock:()=>OUTBOX_NOW,
    budgets:readBudgets,read_fence:readFence,
    max_age_ms:86400000,expiry_ms:172800000});
  const writer = createSecondBrainWriteRequestAdapter(transport,fixture.database.authority,()=>OUTBOX_NOW);
  const spoolRoots = {candidate_dispatch_spool_root:join(fixture.database.root,'candidate-dispatch'),
    candidate_review_spool_root:join(fixture.database.root,'candidate-review')};
  const cliDependencies = {clock:()=>OUTBOX_NOW,memoryOutboxOptions:{...spoolRoots,
    transport_options:{launcherPath:launcher,configPath:join(root,'config.toml')}}};
  const cli = args => execute([...args,'--db',fixture.database.path],cliDependencies);
  const content = fixture.request.payload.content;
  const expectation = memoryRememberArtifact(fixture.request);
  const expected = expectation.artifact;
  const prepared = ownerConfirmed ? prepareMemoryRememberDispatch(fixture.database.authority,
    fixture.request.candidate_id,OUTBOX_NOW,{candidate_review_spool_root:join(fixture.database.root,'candidate-review'),
      candidate_dispatch_spool_root:join(fixture.database.root,'candidate-dispatch')}) : undefined;
  const control = new ControlPlane(fixture.database.authority);
  const previous = ownerConfirmed
    ? {args_json:JSON.stringify(prepared.args),target_json:JSON.stringify(prepared.target)}
    : fixture.database.authority.db.prepare('SELECT args_json,target_json FROM control_command_requests WHERE request_id=?').get(fixture.commandId);
  const action = {schema_version:1,action:'memory.outbox.dispatch',action_level:3,
    request_id:'memory-real-provider',nonce:'memory-real-provider-nonce',reversible:false,
    requested_by:'principal:owner',requested_at:OUTBOX_NOW.toISOString(),
    expires_at:new Date(OUTBOX_NOW.getTime()+900000).toISOString(),target:JSON.parse(previous.target_json),
    args:{...JSON.parse(previous.args_json),expected_artifact:expected}};
  const staged = runtimeCli ? (await cli(['memory','stage-dispatch',fixture.request.candidate_id])).request
    : control.stage(action,OUTBOX_NOW);
  control.decide(signCommandApproval({schema_version:1,receipt_id:'memory-real-provider-receipt',
    request_id:staged.request_id,decision:'approve',command_digest:staged.command_digest,
    signer_principal_id:'principal:owner',authenticated_session_id:'isolated-acceptance',key_id:'decision-test',
    algorithm:'Ed25519',issued_at:OUTBOX_NOW.toISOString(),not_before:OUTBOX_NOW.toISOString(),
    expires_at:staged.expires_at,nonce:'memory-real-provider-receipt-nonce',max_uses:1,status:'issued'},
    localKey(fixture.database.authority)),OUTBOX_NOW);
  const service = new MemoryOutboxService({authority:fixture.database.authority,writer,reader,clock:()=>OUTBOX_NOW,
    candidate_dispatch_spool_root:join(fixture.database.root,'candidate-dispatch'),
    candidate_review_spool_root:join(fixture.database.root,'candidate-review')});
  const query = recordLimit ? 'a'.repeat(60) : recordSet ? '기억' : content;
  const initial = await reader.search(query);
  let claimed, queued, dispatched;
  if (runtimeCli) {
    dispatched = (await cli(['control','execute',staged.request_id])).execution;
    assert.equal(dispatched.state,'uncertain');
    queued = service.get(dispatched.result.outbox_id);
    claimed = new MemoryOutboxRecordReader(fixture.database.authority,spoolRoots).command(queued.outbox_id);
  } else {
    claimed = control.claim(staged.request_id,'real-provider-worker',OUTBOX_NOW);
    queued = service.enqueue(claimed);
    dispatched = await service.runOnce('real-provider-worker',1);
  }
  const statusArgs = () => ({request_id:fixture.request.request_id,
    ...(deleted === undefined ? {} : {read_fence:deleted.statusFence()})});
  const accepted = await transport.call('sb_request_status',statusArgs());
  const applied = provider('apply');
  const status = await transport.call('sb_request_status',statusArgs());
  if(duringCompile) compiler = await pausedCompile({python,sb,config:join(root,'config.toml')});
  const readStarted = performance.now();
  const reconciled = runtimeCli ? (await cli(['memory','outbox','--once','--limit','1'])).cycle
    : await service.reconcileOnce('real-provider-worker',1);
  const reused = await reader.readPage(expected.page_id);
  const recent = await reader.recentChanges(1);
  secondTransport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const secondReader = createSecondBrainReadAdapter({transport:secondTransport,contract_profile:'schema4',budget_profile:budgetProfile,clock:()=>OUTBOX_NOW,
    budgets:readBudgets,read_fence:readFence,
    max_age_ms:86400000,expiry_ms:172800000});
  const shared = await secondReader.readPage(expected.page_id);
  const compileReadMs = duringCompile ? performance.now()-readStarted : null;
  const compiled = compiler === undefined ? undefined : await compiler.finish();
  // Simulate a duplicate network delivery of exactly the already accepted envelope.
  const replay = await transport.call('sb_write_request',{request:fixture.request});
  const idle = provider('apply');
  const repeated = await service.runOnce('real-provider-worker',1);
  const terminalReplay = service.get(queued.outbox_id)?.state === 'settled' ? service.enqueue(claimed) : undefined;
  const reviewFiles = readdirSync(join(fixture.database.root,'candidate-review'));
  const result = {input_mode:ownerConfirmed ? 'owner_confirmed_inference' : 'verified_fixture',
    runtime_cli:runtimeCli,control_state:control.get(staged.request_id)?.state,after_delete:deleted?.result ?? null,
    during_compile:duringCompile,compile_read_ms:compileReadMs,compile_completed:compiled?.event ?? null,
    approval_rollback_recovered:approvalRollback,
    record_set:recordSet,record_limit:recordLimit,budget_profile:budgetProfile,sensitive,initial:initial.kind,dispatched,accepted:accepted.value?.state,applied,
    provider_status:status.value?.state,reconciled,outbox:service.get(queued.outbox_id)?.state,
    reused:reused.kind,reuse_code:reused.code,evidence_count:reused.evidence?.length,
    recent:recent.kind,second_client:shared.kind,replayed:replay.value?.replayed,
    reapply:idle.state,redispatched:repeated.dispatched,terminal_replay:terminalReplay?.state ?? null,
    remaining_review_files:reviewFiles.length,cleanup_error:reconciled.cleanup_error ?? null,
    control_error:reconciled.control_error ?? null};
  console.log(JSON.stringify(result));
  assert.equal(result.accepted,'pending');
  assert.equal(result.provider_status,'proved');
  assert.equal(result.outbox,'settled');
  if (runtimeCli) assert.equal(result.control_state,'completed');
  assert.equal(result.reused,'current');
  assert.equal(result.evidence_count,expectation.record_texts.length);
  if (sensitive) assert(reused.evidence.every(row=>row.sensitivity==='sensitive' && row.excerpt===null && row.omission==='policy_redacted'));
  assert.equal(result.recent,'current');
  assert.equal(result.second_client,'current');
  assert.deepEqual(shared.evidence?.map(row=>row.record?.record_id),reused.evidence?.map(row=>row.record?.record_id));
  assert.equal(result.replayed,true);
  assert.equal(result.reapply,'idle');
  assert.equal(result.redispatched,0);
  assert.equal(result.terminal_replay,'settled');
  assert.equal(result.remaining_review_files,0);
  assert.equal(result.cleanup_error,null);
  assert.equal(result.control_error,null);
} finally {
  await compiler?.close();
  await transport?.close();
  await secondTransport?.close();
  if (fixture) closeMemoryDatabase(fixture.database);
  process.chdir(initialCwd);
  releaseFixture(root);
  rmSync(root,{recursive:true,force:true});
}
