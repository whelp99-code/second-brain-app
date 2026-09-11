// Actual JARVIS-owned deletion chain -> provider restore -> JARVIS reference reader.
// All sources, keys and authority are isolated fixtures; no operational activation.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, unlinkSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {referenceEffectFixture} from './reference_effect_fixture.mjs';
import {checkRestoredScope} from './restore-scoped-client.mjs';
const build = resolve(process.argv[2]);
const sb = fileURLToPath(new URL('..', import.meta.url));
const load = name => import(pathToFileURL(join(build,name)).href);
const root = mkdtempSync('/var/tmp/sb-jarvis-restore-');
const python = join(sb,'.venv/bin/python');
const run = (...args) => execFileSync(python,args,{cwd:sb,encoding:'utf8',timeout:120000});
run('-m','tests.fixtures.jarvis_memory_provider','init',root);
const configPath = join(root,'config.toml');
writeFileSync(configPath,`knowledge_registry = ${JSON.stringify(join(root,'registry.sqlite'))}\n`+readFileSync(configPath,'utf8'),{mode:0o600});
run('-m','tests.fixtures.jarvis_memory_provider','seed',root,'--content','DeleteAlpha synthetic obsolete memory');
run('scripts/restore-probe.py','seed-keep',root);
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
const launcher = join(root,'mcp');
writeFileSync(launcher,`#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m sb.mcp\n`,{mode:0o700});
const {memoryDatabase,closeMemoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
const {memoryReadFenceFixture} = await load('tests/fixtures/memory-read-fence.js');
const {createProductionMemoryReference} = await load('src/memory-reference-production.js');
const {createProductionMemoryReadFence} = await load('src/memory-read-fence-production.js');
const database = await memoryDatabase();
const {config,key} = memoryReadFenceFixture(database,new Date(Date.now()+86400000).toISOString());
const {backupSqlite, restoreSqlite} = await load('src/personal-os-backup.js');
function countReceipts(authority) {
  const count = table => {
    try { return Number(authority.db.prepare(`SELECT COUNT(*) AS c FROM ${table}`).get()?.c ?? 0); }
    catch { return 0; }
  };
  return {
    tombstone_chain: count('memory_tombstone_chain'),
    deletion_proofs: count('memory_deletion_proofs'),
    gjc_intents: count('gjc_intents'),
  };
}
let runtime = createProductionMemoryReference(database.authority,{
  read_fence_config:config,projection_key:Buffer.alloc(32,7),
  transport_options:{contractProfile:'task32-schema4',launcherPath:launcher,configPath:join(root,'config.toml')},
});
let effects;
try {
  const read = query => runtime.reader.read(query,{max_records:8,max_record_bytes:4096,max_bytes:8000});
  const before = await read('DeleteAlpha');
  assert.equal(before.payload.records.length,1);
  const scenarioStarted = Date.now();
  const backup = JSON.parse(run('scripts/restore-probe.py','backup',root));
  const failureBegan = Date.now();
  const journals = JSON.parse(run('scripts/restore-probe.py','journal-loss-from-backup',root));
  assert.equal(journals.journals_dropped,true);
  assert.equal(journals.journals_restored_from_backup,true);
  effects = await referenceEffectFixture({load,database,key,config,launcher,root,sb,python});
  const deleted = await effects.apply('forget',before.payload.records.find(row=>row.text.includes('DeleteAlpha')).record);
  const jarvisDurableAt = Date.now();
  assert.equal(deleted.tombstone_sequence,1);
  const receiptsAtBackup = countReceipts(database.authority);
  mkdirSync(join(root,'jarvis-authority-backup'),{recursive:true});
  const jarvisBackup = await backupSqlite({
    sourcePath:database.path,
    destPath:join(root,'jarvis-authority-backup','jarvis-rehearsal.sqlite'),
  });
  database.authority.configureGjc(root,'crash-session',true);
  const extraIntent = database.authority.createGjcIntent(
    'sync',{session_id:'crash-session',turn_id:'post-backup'},'post-backup-key',
  );
  const receiptsAfterExtra = countReceipts(database.authority);
  assert.ok(receiptsAfterExtra.gjc_intents > receiptsAtBackup.gjc_intents);
  await runtime.close();
  await effects.close();
  database.authority.close();
  for (const suffix of ['','-wal','-shm']) {
    try { unlinkSync(database.path + suffix); } catch { /* missing sidecar */ }
  }
  const jarvisRestored = restoreSqlite({
    backupPath:jarvisBackup.destPath, destPath:database.path,
  });
  database.authority.reopen();
  const receiptsAfterRestore = countReceipts(database.authority);
  assert.equal(receiptsAfterRestore.gjc_intents, receiptsAtBackup.gjc_intents);
  assert.equal(
    database.authority.db.prepare('SELECT intent_id FROM gjc_intents WHERE intent_id=?').get(extraIntent),
    undefined,
  );
  const junk = join(root,'jarvis-authority-backup','junk.sqlite');
  writeFileSync(junk,'not-a-database');
  let oldVersionRefused;
  try {
    restoreSqlite({
      backupPath:junk,
      destPath:join(root,'jarvis-authority-backup','bad-dest.sqlite'),
    });
  } catch (error) {
    oldVersionRefused = error instanceof Error && 'code' in error ? error.code : String(error);
  }
  assert.equal(oldVersionRefused,'E_RESTORE_FAILED');
  runtime = createProductionMemoryReference(database.authority,{
    read_fence_config:config,projection_key:Buffer.alloc(32,7),
    transport_options:{contractProfile:'task32-schema4',launcherPath:launcher,configPath:join(root,'config.toml')},
  });
  effects = await referenceEffectFixture({load,database,key,config,launcher,root,sb,python});
  const authorize = createProductionMemoryReadFence(database.authority,config,'memory_status');
  const fence = authorize(new Date());
  assert.equal(fence.tombstone_sequence,1);
  const restoreBegan = Date.now();
  const restored = JSON.parse(execFileSync(python,['scripts/restore-probe.py','restore',root],
    {cwd:sb,encoding:'utf8',timeout:120000,input:JSON.stringify(fence)}));
  assert.equal(restored.tombstone_sequence,fence.tombstone_sequence);
  assert.equal(restored.tombstone_set_root,fence.tombstone_set_root);
  assert.equal(restored.blocked_matches,0);
  assert.equal(restored.scan_errors,0);
  assert.equal((await read('DeleteAlpha')).payload.records.length,0);
  const keep = await read('KeepBeta');
  const sbReadableAt = Date.now();
  assert.equal(keep.payload.records.length,1);
  assert(keep.payload.records[0].text.includes('KeepBeta'));
  const connected = new Map();
  let release, reject;
  const gate = new Promise((resolve,rejectGate)=>{release=resolve;reject=rejectGate;});
  const timer = setTimeout(()=>reject(new Error('concurrent restore clients did not rendezvous')),20000);
  let independentRevocations = 0;
  const coordinate = async (id,client) => {
    connected.set(id,client);
    if (connected.size === 2) {
      const [first,second] = [...connected.values()];
      try {
        for (const [revoked,allowed] of [[first,second],[second,first]]) {
          revoked.revoke();
          await assert.rejects(revoked.read,error=>error.code==='MEMORY_ACCESS_SCOPE_UNAVAILABLE');
          assert.equal((await allowed.read()).pages.length,1);
          revoked.restore();
          independentRevocations++;
        }
        release();
      } catch (error) {reject(error);}
      finally {first.restore();second.restore();clearTimeout(timer);}
    }
    await gate;
  };
  let outcomes;
  try {
    outcomes = await Promise.allSettled(['restore','restore-peer'].map(clientId=>
      checkRestoredScope({load,database,config,root,launcher,pageId:restored.surviving_page_id,clientId,coordinate})));
  } finally {clearTimeout(timer);}
  for (const outcome of outcomes) assert.equal(outcome.status,'fulfilled',String(outcome.reason));
  const [scoped,peer] = outcomes.map(outcome=>outcome.value);
  const scopedAvailableAt = Date.now();
  assert.equal(independentRevocations,2);
  assert.notEqual(scoped.agent,peer.agent);
  assert.notEqual(scoped.session,peer.session);
  assert.deepEqual(scoped.generation,peer.generation);
  assert.equal(scoped.generation.generation_id,restored.generation_id);
  assert.match(scoped.page_content_digest,/^sha256:[0-9a-f]{64}$/);
  assert.equal(scoped.page_content_digest,peer.page_content_digest);
  const written = JSON.parse(run('scripts/seed-distinct-remember.py',root));
  const newWriteAvailableAt = Date.now();
  assert.equal(written.state,'proved');
  writeFileSync(join(root,'trusted-fence.json'),JSON.stringify(fence));
  const writerLease = JSON.parse(run('scripts/writer-lease-on-root.py',root));
  assert.equal(writerLease.writer_busy,true);
  assert.ok(writerLease.queue_depth > 0);
  assert.equal(writerLease.empty_queue,false);
  const deletedAfterRestore = await effects.apply('forget',(await read('KeepBeta')).payload.records[0].record);
  assert.equal(deletedAfterRestore.tombstone_sequence,2);
  assert.equal((await read('KeepBeta')).payload.records.length,0);
  const secondFence = authorize(new Date());
  assert.equal(secondFence.tombstone_sequence,2);
  const restoredAgain = JSON.parse(execFileSync(python,['scripts/restore-probe.py','restore',root],
    {cwd:sb,encoding:'utf8',timeout:120000,input:JSON.stringify(secondFence)}));
  assert.equal(restoredAgain.tombstone_sequence,2);
  assert.equal(restoredAgain.tombstone_set_root,secondFence.tombstone_set_root);
  assert.equal(restoredAgain.surviving_page_id,null);
  assert.equal(restoredAgain.blocked_matches,0);
  assert.equal(restoredAgain.scan_errors,0);
  assert.equal((await read('DeleteAlpha')).payload.records.length,0);
  assert.equal((await read('KeepBeta')).payload.records.length,0);
  const result = {root,backup,journals,deleted,restored,scoped,peer,deleted_after_restore:deletedAfterRestore,
    restored_again:restoredAgain,second_restore_records:0,concurrent_clients:2,independent_revocations:independentRevocations,shared_restored_memory_equal:true,jarvis_owned_high_water:secondFence.tombstone_sequence,
    deleted_records:0,first_restore_surviving_records:1,model_calls:0,
    rpo_source_generation_id:backup.source_generation_id,
    rpo_sb: {
      last_durable_at: backup.created_at,
      last_durable_generation_id: backup.source_generation_id,
      durable_pages_at_backup: backup.durable_page_count,
      writes_after_backup_before_failure: 0,
      crash_loss_records: 0,
      restored_generation_id: restored.generation_id,
    },
    rpo_jarvis: {
      last_durable_request_id: deleted.request_id,
      last_durable_proof_id: deleted.proof_id,
      last_durable_at_ms: jarvisDurableAt,
      tombstone_sequence_before_restore: deleted.tombstone_sequence,
      restored_tombstone_sequence: restored.tombstone_sequence,
      revoked_records_held: 1,
      receipts_at_backup: receiptsAtBackup,
      receipts_after_extra: receiptsAfterExtra,
      receipts_after_restore: receiptsAfterRestore,
      crash_loss_receipts: receiptsAfterExtra.gjc_intents - receiptsAfterRestore.gjc_intents,
      lost_intent_id: extraIntent,
      lost_intent_present_after_restore: false,
      backup_sha256: jarvisBackup.sha256,
      restore_sha256: jarvisRestored.sha256,
      old_version_refused: oldVersionRefused,
      keep_beta_readable: true,
    },
    writer_lease: writerLease,
    rto: {
      failure_began_ms: failureBegan,
      restore_began_ms: restoreBegan,
      sb_first_read_ms: sbReadableAt,
      scoped_available_ms: scopedAvailableAt,
      new_write_available_ms: newWriteAvailableAt,
      restore_probe_ms: restored.restore_duration_ms,
      restore_to_readable_ms: sbReadableAt - restoreBegan,
      failure_to_first_read_ms: sbReadableAt - failureBegan,
      failure_to_work_available_ms: newWriteAvailableAt - failureBegan,
      scenario_ms: Date.now() - scenarioStarted,
    },
    rto_restore_to_readable_ms: sbReadableAt - restoreBegan,
    written,
    scope:'Actual JARVIS chain/effect proof/fence/reference reader with isolated fixtures; synthetic project scopes; not operational/native acceptance'};
  writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
} finally {
  await effects?.close();
  await runtime.close();
  closeMemoryDatabase(database);
}
