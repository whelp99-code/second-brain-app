// Built JARVIS + separate OS processes; synthetic authority/provider, no operational data.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const [build, mode, root] = process.argv.slice(2);
assert(build?.startsWith('/')); process.umask(0o077); process.chdir(build);
const load = path => import(pathToFileURL(join(build, 'dist', path)));
const {correctionPreparedFixture} = await load('tests/fixtures/memory-correction-control.js');
const {MemoryProjectionAuthority} = await load('src/memory-projection-authority.js');
const {AuthorityDb} = await load('src/db.js');
const deny = f => new MemoryProjectionAuthority(f.db).quarantineUnresolved({kind:'dashboard_projection',
  id:f.candidate.candidate_id, component_id:f.candidate.candidate_id}, f.runtime.clock());
const code = value => error => error.code === value;
let result;

if (mode === 'seed') {
  const f = await correctionPreparedFixture();
  try {
    const locator = readdirSync(f.runtime.spool_root)[0];
    const staged = JSON.parse(readFileSync(join(f.runtime.spool_root, locator), 'utf8'));
    f.runtime.barriers.reach = async () => {deny(f); throw new Error('interrupted-before-retirement');};
    await assert.rejects(f.saga.dispatch(f.claim), /interrupted-before-retirement/);
    assert.equal(f.writer.calls.length, 0);
    assert.deepEqual(f.db.db.prepare('SELECT state,dispatch_fence FROM memory_correction_requests').get(),
      {state:'queued', dispatch_fence:0});
    writeFileSync(join(root, 'state.json'), JSON.stringify({database_path:f.database.path,
      fixture_root:f.root, database_root:f.database.root, anchors_root:f.database.anchorsRoot,
      spool_root:f.runtime.spool_root, locator, staged, candidate_id:f.candidate.candidate_id,
      now:f.runtime.clock().toISOString()}));
    result = {mode, pid:process.pid, state:'queued', dispatch_attempts:0, provider_calls:0,
      interrupted_after_tombstone:true};
  } finally {await f.databaseRuntime.close(); f.db.close();}
 } else if (mode === 'restart') {
  const state = JSON.parse(readFileSync(join(root, 'state.json'), 'utf8'));
  const db = new AuthorityDb(state.database_path); await db.migrate();
  try {
    const {MemoryCorrectionStore} = await load('src/memory-correction-store.js');
    const correction = db.db.prepare('SELECT * FROM memory_correction_requests').get();
    assert.equal(correction.state, 'queued');
    assert.throws(()=>new MemoryCorrectionStore(db).beginDispatch(correction.correction_id, new Date(state.now)),
      code('MEMORY_CANDIDATE_SUPPRESSED'));
    assert.deepEqual(db.db.prepare('SELECT COUNT(*) AS count FROM memory_correction_attempts').get(), {count:0});
    assert.equal(JSON.parse(readFileSync(join(state.spool_root, state.locator), 'utf8')).content, state.staged.content);
    assert.deepEqual(db.db.prepare('SELECT accepted_through_sequence,active_lane_id,fence FROM memory_effect_dispatch_cursor').get(),
      {accepted_through_sequence:0, active_lane_id:null, fence:0});
    result = {mode, pid:process.pid, state:'queued', suppressed_dispatch_rejected:true, correction_attempts:0,
      retained_spool_present:true, accepted_through_sequence:0, automatic_recovery_complete:false};
  } finally {db.close();}
} else if (mode === 'adapter') {
  const f = await correctionPreparedFixture(); let calls = 0;
  try {
    const {createSecondBrainWriteRequestAdapter} = await load('src/second-brain-write-adapter.js');
    const adapter = createSecondBrainWriteRequestAdapter({call:async()=>{calls++; return {kind:'no_data',reason:'empty_result'};},
      restart:async()=>{}, close:async()=>{}, diagnostics:()=>[]}, f.db, f.runtime.clock);
    f.runtime.writer.write = async request => {
      assert.equal((await adapter.write(request)).code, 'SECOND_BRAIN_WRITE_RESULT_INVALID'); assert.equal(calls, 1);
      deny(f); const rejected = await adapter.write(request);
      assert.equal(rejected.code, 'SECOND_BRAIN_WRITE_AUTHORITY_INVALID'); assert.equal(calls, 1); return rejected;
    };
    const record = await f.saga.dispatch(f.claim);
    assert.equal(record.state, 'reconciling');
    assert.equal((await f.saga.reconcile(record.correction_id)).state, 'reconciling');
    result = {mode, pid:process.pid, valid_request_transport_calls:1, post_suppression_additional_calls:0,
      observation_continues:true};
  } finally {await f.close();}
} else {
  const fixture = mkdtempSync('/var/tmp/jarvis-v2-suppression-'); const cases = [];
  for (const worker of ['seed','restart','adapter']) {
    const run = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, worker, fixture],
      {encoding:'utf8', timeout:30_000, maxBuffer:1024*1024, env:{...process.env, TMPDIR:'/var/tmp'}});
    assert.equal(run.status, 0, run.stderr); cases.push(JSON.parse(run.stdout));
  }
  const manifest = JSON.parse(readFileSync(join(build, 'dist/build-metadata.json'), 'utf8'));
  result = {status:'passed', root:fixture, build, cases, build_artifact_digest:manifest.artifact.digest,
    provider:'deterministic transport fixture', operational_data_used:false, native_model_calls:0,
    retained_artifacts:'synthetic authority, keys and held spool retained for audit',
    full_goal_complete:false};
  writeFileSync(join(fixture, 'result.json'), JSON.stringify(result, null, 2)+'\n');
}
console.log(JSON.stringify(result, null, 2));
