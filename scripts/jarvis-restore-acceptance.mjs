// Actual JARVIS-owned deletion chain -> provider restore -> JARVIS reference reader.
// All sources, keys and authority are isolated fixtures; no operational activation.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
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
const runtime = createProductionMemoryReference(database.authority,{
  read_fence_config:config,projection_key:Buffer.alloc(32,7),
  transport_options:{contractProfile:'task32-schema4',launcherPath:launcher,configPath:join(root,'config.toml')},
});
let effects;
try {
  const read = query => runtime.reader.read(query,{max_records:8,max_record_bytes:4096,max_bytes:8000});
  const before = await read('DeleteAlpha');
  assert.equal(before.payload.records.length,1);
  const backup = JSON.parse(run('scripts/restore-probe.py','backup',root));
  effects = await referenceEffectFixture({load,database,key,config,launcher,root,sb,python});
  const deleted = await effects.apply('forget',before.payload.records.find(row=>row.text.includes('DeleteAlpha')).record);
  assert.equal(deleted.tombstone_sequence,1);
  const authorize = createProductionMemoryReadFence(database.authority,config,'memory_status');
  const fence = authorize(new Date());
  assert.equal(fence.tombstone_sequence,1);
  const restored = JSON.parse(execFileSync(python,['scripts/restore-probe.py','restore',root],
    {cwd:sb,encoding:'utf8',timeout:120000,input:JSON.stringify(fence)}));
  assert.equal(restored.tombstone_sequence,fence.tombstone_sequence);
  assert.equal(restored.tombstone_set_root,fence.tombstone_set_root);
  assert.equal(restored.blocked_matches,0);
  assert.equal(restored.scan_errors,0);
  assert.equal((await read('DeleteAlpha')).payload.records.length,0);
  const keep = await read('KeepBeta');
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
  assert.equal(independentRevocations,2);
  assert.notEqual(scoped.agent,peer.agent);
  assert.notEqual(scoped.session,peer.session);
  assert.deepEqual(scoped.generation,peer.generation);
  assert.equal(scoped.generation.generation_id,restored.generation_id);
  assert.match(scoped.page_content_digest,/^sha256:[0-9a-f]{64}$/);
  assert.equal(scoped.page_content_digest,peer.page_content_digest);
  const deletedAfterRestore = await effects.apply('forget',keep.payload.records[0].record);
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
  const result = {root,backup,deleted,restored,scoped,peer,deleted_after_restore:deletedAfterRestore,
    restored_again:restoredAgain,second_restore_records:0,concurrent_clients:2,independent_revocations:independentRevocations,shared_restored_memory_equal:true,jarvis_owned_high_water:secondFence.tombstone_sequence,
    deleted_records:0,first_restore_surviving_records:1,model_calls:0,
    scope:'Actual JARVIS chain/effect proof/fence/reference reader with isolated fixtures; synthetic project scopes; not operational/native acceptance'};
  writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
} finally {
  await effects?.close();
  await runtime.close();
  closeMemoryDatabase(database);
}
