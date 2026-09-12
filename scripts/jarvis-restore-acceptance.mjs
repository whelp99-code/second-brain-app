// Actual JARVIS-owned deletion chain -> provider restore -> JARVIS reference reader.
// All sources, keys and authority are isolated fixtures; no operational activation.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, unlinkSync, writeFileSync} from 'node:fs';
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
const {memoryEffectDigest} = await load('src/second-brain-effect-v2.js');
const {MEMORY_EFFECT_LANE_PREFIX} = await load('src/second-brain-effect-v2-contract.js');
const database = await memoryDatabase();
const {config,key} = memoryReadFenceFixture(database,new Date(Date.now()+86400000).toISOString());
const {backupSqlite, restoreSqlite} = await load('src/personal-os-backup.js');
function countReceipts(authority) {
  const count = table => {
    const row = authority.db.prepare(`SELECT COUNT(*) AS c FROM ${table}`).get();
    return Number(row.c);
  };
  return {
    tombstone_chain: count('memory_tombstone_chain'),
    deletion_proofs: count('memory_deletion_proofs'),
    gjc_intents: count('gjc_intents'),
  };
}
function tombstoneIds(authority) {
  return authority.db.prepare('SELECT tombstone_id FROM memory_tombstone_chain ORDER BY sequence').all()
    .map(row => row.tombstone_id);
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
  const idsAtBackup = tombstoneIds(database.authority);
  mkdirSync(join(root,'jarvis-authority-backup'),{recursive:true});
  const jarvisBackup = await backupSqlite({
    sourcePath:database.path,
    destPath:join(root,'jarvis-authority-backup','jarvis-rehearsal.sqlite'),
  });
  const extraWritten = JSON.parse(run('scripts/seed-extra-lost.py',root));
  assert.equal(extraWritten.state,'proved');
  const extraBeforeCrash = await read('ExtraLostAfterBackup');
  assert.equal(extraBeforeCrash.payload.records.length,1);
  const extraResolved = await effects.resolve(extraBeforeCrash.payload.records[0].record);
  assert.equal(extraResolved.kind,'data',JSON.stringify(extraResolved));
  const extraTarget = extraResolved.value;
  const extraTargets = [extraTarget];
  const extraTargetDigest = memoryEffectDigest('target_manifest',{targets:extraTargets});
  const extraScope = {format:'none',sensitivity_classes:[extraTarget.sensitivity],valid_from:extraTarget.valid_from,
    valid_until:extraTarget.valid_until,max_records:1,max_bytes:4096,source_owner_classes:[extraTarget.source_owner_class]};
  const extraScopeDigest = memoryEffectDigest('target_scope',{target_digests:[extraTarget.target_digest],scope:extraScope});
  const extraPayload = {disposition:'owner_requested',erasure_claim:'provider_local_suppression',external_receipts:[]};
  const extraAppended = effects.chain.append({
    operation:'forget',
    lane_id: MEMORY_EFFECT_LANE_PREFIX.deletion + extraTargetDigest.slice(7),
    targets: extraTargets,
    target_manifest_digest: extraTargetDigest,
    scope_digest: extraScopeDigest,
    authority_receipt_digest: `sha256:${'d'.repeat(64)}`,
    payload_digest: memoryEffectDigest('effect_payload',extraPayload),
    effective_at: new Date().toISOString(),
  });
  assert.equal(extraAppended.entry.sequence,2);
  const receiptsAfterExtra = countReceipts(database.authority);
  const idsAfterExtra = tombstoneIds(database.authority);
  assert.ok(idsAfterExtra.includes(extraAppended.entry.tombstone_id));
  await runtime.close();
  await effects.close();
  const crashBegan = Date.now();
  for (const suffix of ['','-wal','-shm']) {
    try { unlinkSync(database.path + suffix); } catch { /* missing sidecar */ }
  }
  database.authority.close();
  const jarvisRestored = restoreSqlite({
    backupPath:jarvisBackup.destPath, destPath:database.path,
  });
  database.authority.reopen();
  const jarvisRestoredAt = Date.now();
  const receiptsAfterRestore = countReceipts(database.authority);
  const idsAfterRestore = tombstoneIds(database.authority);
  assert.equal(receiptsAfterRestore.tombstone_chain, receiptsAtBackup.tombstone_chain);
  assert.deepEqual(idsAfterRestore, idsAtBackup);
  assert.equal(idsAfterRestore.includes(extraAppended.entry.tombstone_id), false);
  const destKeep = join(root,'jarvis-authority-backup','existing-dest.sqlite');
  copyFileSync(jarvisBackup.destPath, destKeep);
  const destKeepHash = createHash('sha256').update(readFileSync(destKeep)).digest('hex');
  let missingPreserved;
  try {
    restoreSqlite({backupPath:join(root,'jarvis-authority-backup','missing.sqlite'), destPath:destKeep});
  } catch (error) {
    missingPreserved = error instanceof Error && 'code' in error ? error.code : String(error);
  }
  assert.equal(missingPreserved,'E_RESTORE_FAILED');
  assert.equal(createHash('sha256').update(readFileSync(destKeep)).digest('hex'), destKeepHash);
  const junk = join(root,'jarvis-authority-backup','junk.sqlite');
  writeFileSync(junk,'not-a-database');
  let invalidBackupRefused;
  try {
    restoreSqlite({backupPath:junk, destPath:destKeep});
  } catch (error) {
    invalidBackupRefused = error instanceof Error && 'code' in error ? error.code : String(error);
  }
  assert.equal(invalidBackupRefused,'E_RESTORE_FAILED');
  assert.equal(createHash('sha256').update(readFileSync(destKeep)).digest('hex'), destKeepHash);
  const oldSchema = join(root,'jarvis-authority-backup','old-schema.sqlite');
  execFileSync(python,['-c',
    'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute("create table sentinel(id text)"); db.commit()',
    oldSchema],{cwd:sb});
  const oldRestored = restoreSqlite({
    backupPath:oldSchema, destPath:join(root,'jarvis-authority-backup','old-restored.sqlite'),
  });
  const {AuthorityDb} = await load('src/db.js');
  let incompatibleAuthority;
  const incompatible = new AuthorityDb(oldRestored.destPath);
  try {
    await incompatible.initialize();
  } catch (error) {
    incompatibleAuthority = error instanceof Error && 'code' in error ? error.code : String(error);
  } finally {
    incompatible.close();
  }
  assert.ok(incompatibleAuthority);
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
  assert.equal((await read('ExtraLostAfterBackup')).payload.records.length,0);
  const sbReceiptAfterRestore = JSON.parse(run('scripts/lookup-request.py',root,extraWritten.request_id));
  assert.equal(sbReceiptAfterRestore.present,true);
  assert.equal(sbReceiptAfterRestore.state,'proved');
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
  const writerLease = JSON.parse(run('scripts/writer-lease-on-root.py',root));
  assert.equal(writerLease.writer_busy,true);
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
  writeFileSync(join(root,'trusted-fence.json'),JSON.stringify(secondFence));
  writeFileSync(join(root,'recovery.env'), [
    `export ROOT=${root}`,
    `export BACKUP=${join(root,'jarvis-authority-backup','jarvis-rehearsal.sqlite')}`,
    `export DEST=${join(root,'jarvis-authority-backup','restored.sqlite')}`,
    `export FENCE=${join(root,'trusted-fence.json')}`,
    `export AUTHORITY=${database.path}`,
    `export AUTHORITY_ROOT=${database.root}`,
    `export JARVIS=${build}`,
  ].join('\n')+'\n');
  const expiredFence = {...secondFence, expires_at: new Date(Date.now()-1000).toISOString()};
  let expiredFenceRefused;
  try {
    execFileSync(python,['scripts/restore-probe.py','restore',root],
      {cwd:sb,encoding:'utf8',timeout:120000,input:JSON.stringify(expiredFence)});
  } catch (error) {
    expiredFenceRefused = String(error);
  }
  assert.match(String(expiredFenceRefused), /TOMBSTONE_FENCE_REQUIRED|TOMBSTONE_SET_STALE/);
  const freshFence = JSON.parse(execFileSync(process.execPath,[join(sb,'scripts/issue-restore-fence.mjs')],{
    cwd:sb,encoding:'utf8',timeout:30000,env:{...process.env,JARVIS:build,AUTHORITY:database.path,AUTHORITY_ROOT:database.root,FENCE:join(root,'trusted-fence.json')},
  }));
  assert.equal(freshFence.tombstone_sequence,secondFence.tombstone_sequence);
  const sameRootRestore = JSON.parse(execFileSync(python,['scripts/restore-probe.py','restore',root],
    {cwd:sb,encoding:'utf8',timeout:120000,input:JSON.stringify(freshFence)}));
  assert.equal(sameRootRestore.tombstone_sequence,freshFence.tombstone_sequence);
  const result = {root,backup,journals,deleted,restored,scoped,peer,deleted_after_restore:deletedAfterRestore,
    restored_again:restoredAgain,second_restore_records:0,concurrent_clients:2,independent_revocations:independentRevocations,shared_restored_memory_equal:true,jarvis_owned_high_water:secondFence.tombstone_sequence,
    deleted_records:0,first_restore_surviving_records:1,model_calls:0,
    rpo_source_generation_id:backup.source_generation_id,
    rpo_sb: {
      last_durable_at: backup.created_at,
      last_durable_generation_id: backup.source_generation_id,
      durable_pages_at_backup: backup.durable_page_count,
      writes_after_backup_before_failure: 1,
      post_backup_accepted_request_id: extraWritten.request_id,
      post_backup_remember_lost_on_generation_restore: true,
      crash_loss_records: 1,
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
      crash_loss_accepted_receipts: receiptsAfterExtra.tombstone_chain - receiptsAfterRestore.tombstone_chain,
      ids_at_backup: idsAtBackup,
      ids_after_extra: idsAfterExtra,
      ids_after_restore: idsAfterRestore,
      lost_jarvis_tombstone_id: extraAppended.entry.tombstone_id,
      lost_jarvis_tombstone_present_after_restore: idsAfterRestore.includes(extraAppended.entry.tombstone_id),
      sb_post_backup_request_id: extraWritten.request_id,
      sb_post_backup_receipt_after_restore: sbReceiptAfterRestore,
      loss_mode: 'unclean_unlink_while_open',
      dest_preserved_on_missing_backup: missingPreserved,
      dest_preserved_on_invalid_backup: invalidBackupRefused,
      backup_sha256: jarvisBackup.sha256,
      restore_sha256: jarvisRestored.sha256,
      invalid_backup_refused: invalidBackupRefused,
      incompatible_authority: incompatibleAuthority,
      keep_beta_readable: true,
    },
    same_root_restore: {tombstone_sequence:sameRootRestore.tombstone_sequence, blocked_matches:sameRootRestore.blocked_matches},
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
      jarvis_crash_to_reopen_ms: jarvisRestoredAt - crashBegan,
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
