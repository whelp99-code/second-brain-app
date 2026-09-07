// Opt-in V2 correction against an isolated real provider and two JARVIS readers.
// Delegation uses a synthetic owner fixture; this is not the full correction UI.
import assert from 'node:assert/strict';
import {correctionControlFixture} from './jarvis-correction-control-fixture.mjs';
import {execFileSync} from 'node:child_process';
import {createHash, createPublicKey} from 'node:crypto';
import {chmodSync, lstatSync, mkdtempSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const jarvis = resolve(process.argv[2] ?? join(sb, '../Orca-JARVIS'));
const load = path => import(pathToFileURL(join(jarvis, 'dist', path)).href);
const {memoryDatabase, closeMemoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
const {memoryReadFenceFixture} = await load('tests/fixtures/memory-read-fence.js');
const {OUTBOX_NOW:now} = await load('tests/fixtures/memory-outbox-fixture.js');
const {createSecondBrainTransport, createSecondBrainReadAdapter} = await load('src/index.js');
const {SecondBrainEffectService} = await load('src/second-brain-effect-service.js');
const {MemoryTombstoneChain} = await load('src/memory-tombstone-chain.js');
const {createMemoryEffectWriteRequest, memoryEffectDigest} = await load('src/second-brain-effect-v2.js');
const {verifyMemoryDispositionProof} = await load('src/memory-disposition-proof.js');
const {parseMemoryLifecycleObservationManifest} = await load('src/memory-lifecycle-observation-manifest.js');
const hash = value => createHash('sha256').update(value).digest('hex');
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
const root = mkdtempSync(join(tmpdir(), 'sb-jarvis-correction-'));
const provider = mode => JSON.parse(execFileSync(python,
  ['-m', 'tests.fixtures.jarvis_memory_provider', mode, root], {cwd:sb, encoding:'utf8'}) || '{}');
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
const release = path => {
  if (!lstatSync(path).isDirectory()) return;
  chmodSync(path, 0o700);
  for (const name of readdirSync(path)) release(join(path, name));
};
const controlCycle = process.argv.includes('--control-cycle');
let database, transport, secondTransport, lifecycle;
try {
  provider('init');
  const launcher = join(root, 'mcp');
  writeFileSync(launcher, `#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m tests.fixtures.jarvis_memory_provider serve ${quote(root)}\n`, {mode:0o700});
  database = await memoryDatabase();
  const {key,config} = memoryReadFenceFixture(database);
  const publicKey = createPublicKey(key).export({format:'pem',type:'spki'}).toString();
  database.authority.db.prepare(`INSERT INTO memory_provider_proof_keys VALUES
    (?, ?, ?, 'Ed25519', ?, ?, 'active', ?, ?, ?)`)
    .run('provider:key',config.provider_instance_id,'a'.repeat(40),publicKey,hash(publicKey),
      now.toISOString(),new Date(now.getTime()+86400000).toISOString(),now.toISOString());
  transport = createSecondBrainTransport({launcherPath:launcher, configPath:join(root,'config.toml')});
  const effects = new SecondBrainEffectService({authority:database.authority,transport,clock:()=>now,
    writer:{write:async()=>{throw new Error('no implicit writer');}},
    provider_instance_id:config.provider_instance_id,signing_key_id:config.signing_key_id,private_key:key});
  const makeReader = wire => createSecondBrainReadAdapter({transport:wire, contract_profile:'schema4',
    clock:()=>now, max_age_ms:86400000, expiry_ms:172800000,
    budgets:{max_hits:10,max_excerpt_bytes:4096,max_page_bytes:262144,max_total_bytes:262144},
    budget_profile:'record-set-v1',read_fence:()=>effects.readFence('memory_read',now)});
  const reader = makeReader(transport);
  assert.equal(provider('seed').state, 'proved');
  const initial = await reader.search('ExampleAlpha');
  assert.equal(initial.kind, 'current');
  const record = initial.evidence.find(item=>item.record)?.record;
  assert(record);
  const resolved = await effects.resolveTarget({record_id:record.record_id,record_digest:record.record_digest,
    generation_id:record.generation.generation_id,generation_manifest_digest:record.generation.generation_manifest_digest});
  assert.equal(resolved.kind,'data');
  const target = resolved.value;
  const targets = [target];
  const scope = {format:'none',sensitivity_classes:[target.sensitivity],valid_from:target.valid_from,
    valid_until:target.valid_until,max_records:1,max_bytes:4096,source_owner_classes:[target.source_owner_class]};
  const targetDigest = memoryEffectDigest('target_manifest',{targets});
  const scopeDigest = memoryEffectDigest('target_scope',{target_digests:[target.target_digest],scope});
  const content = '정정 기억 첫째\n\n  반복 기억  \r\n \r\n반복 기억\n사용자 [^deadbeef] 기록';
  const payload = {content,content_digest:memoryEffectDigest('effect_content',{content}),
    content_bytes:Buffer.byteLength(content),disposition:'superseded'};
  const laneId = `memcorr:req:v1:${'a'.repeat(64)}`;
  const chain = new MemoryTombstoneChain(database.authority,Buffer.alloc(32,11));
  const staleFence = effects.readFence('memory_read',now);
  let appended, request;
  if (controlCycle) {
    lifecycle = await correctionControlFixture({load,jarvis,database,key,config,transport,targets,scope,content,now,root});
    request = lifecycle.request;
    appended = {high_water:request.tombstone_high_water};
  } else {
  appended = chain.append({operation:'correct',lane_id:laneId,targets,target_manifest_digest:targetDigest,
    scope_digest:scopeDigest,authority_receipt_digest:`sha256:${'c'.repeat(64)}`,
    payload_digest:memoryEffectDigest('effect_payload',payload),effective_at:now.toISOString()});
  const expectedPrior = Object.fromEntries(['provider_instance_id','generation_id','generation_manifest_digest',
    'vault_head','vault_tree','page_blob_oid','page_content_digest','citation_identity_full'].map(name=>[name,target[name]]));
  request = createMemoryEffectWriteRequest({schema_version:2,kind:'memory_effect',provider_instance_id:config.provider_instance_id,
    lane:'correction',lane_id:laneId,operation:'correct',target_manifest_digest:targetDigest,targets,scope,scope_digest:scopeDigest,
    expected_prior:expectedPrior,tombstone_high_water:appended.high_water,tombstone_chain_delta:[appended.entry],
    created_at:now.toISOString(),expires_at:new Date(now.getTime()+600000).toISOString(),payload},
  {principal_id:'principal:owner',signing_key_id:config.signing_key_id,not_before:now.toISOString(),nonce:'fixture-correction-nonce'},key);
  const accepted = await transport.call('sb_write_request',{request});
  assert.equal(accepted.kind,'data',JSON.stringify(accepted));
  assert.equal(accepted.value.state,'pending');
  }
  const changed = await transport.call('sb_write_request',{request:{...request,
    payload:{...payload,content:'changed after approval'}}});
  assert.equal(changed.kind,'error');
  const applied = provider('apply');
  assert.equal(applied.state,'proved',JSON.stringify(applied));
  if (lifecycle) {
    lifecycle.failNextCompletion();
    await assert.rejects(()=>lifecycle.service.reconcilePending(10),/INJECTED_FINAL_EVENT_FAILURE/);
    assert.equal(lifecycle.controlState(),'claimed');
    database.authority.db.exec('DROP TRIGGER fail_correction_completion');
    const before = lifecycle.counts();
    lifecycle.advance();
    await lifecycle.service.reconcilePending(10);
    assert.equal(lifecycle.controlState(),'completed');
    assert.deepEqual(lifecycle.counts(),before);
    assert.equal(before.writes,1);
    assert.equal(before.compactions,1);
  }
  const status = await effects.requestStatus(request.request_id);
  assert.equal(status.kind,'data',JSON.stringify(status));
  assert.equal(status.value.state,'proved');
  const proof = verifyMemoryDispositionProof(database.authority,status.value.proof,{
    ...request,delegation_id:request.delegation.delegation_id,
    delegation_digest:request.delegation.delegation_digest,payload_digest:request.delegation.payload_digest,
    tombstone_sequence:appended.high_water.sequence,tombstone_set_root:appended.high_water.set_root,
  },now);
  const observations = parseMemoryLifecycleObservationManifest(status.value.observations,proof);
  assert.equal(observations.result.kind,'correction');
  assert.equal(observations.result.artifact_match_count,1);
  const stale = await transport.call('sb_read_page',{id:target.page_id,read_fence:staleFence});
  assert.deepEqual(stale,{kind:'error',code:'TOMBSTONE_SET_STALE'});
  const old = await reader.search('ExampleAlpha');
  assert(['current','no_data'].includes(old.kind),JSON.stringify(old));
  assert.equal(old.evidence?.length ?? 0,0,JSON.stringify(old));
  const corrected = await reader.readPage(target.page_id);
  secondTransport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const shared = await makeReader(secondTransport).readPage(target.page_id);
  const replay = await transport.call('sb_write_request',{request});
  assert.equal(replay.kind,'data');
  assert.equal(replay.value.replayed,true);
  assert.equal(provider('apply').state,'idle');
  assert.equal(corrected.kind,'current');
  assert.equal(shared.kind,'current');
  assert.equal(corrected.evidence.length,4);
  const texts = content.replaceAll('[^','\\[\\^').split(/\r\n|\n/).map(line=>line.trim()).filter(Boolean);
  const ordered = [...corrected.evidence].sort((a,b)=>a.record.citation_span_start-b.record.citation_span_start);
  assert.deepEqual(ordered.map(row=>row.record?.content_identity_full),texts.map(hash));
  assert(corrected.evidence.every(row=>row.record?.source_identity_full===hash(`memory-effect:${request.request_id}`)));
  assert.deepEqual(shared.evidence.map(row=>row.record?.record_id),corrected.evidence.map(row=>row.record?.record_id));
  console.log(JSON.stringify({request_id:request.request_id,provider_state:applied.state,
    proof_verified:proof.proof_id,tombstone_sequence:appended.high_water.sequence,
    corrected:corrected.kind,shared:shared.kind,record_count:corrected.evidence.length,
    all_content_digests_matched:true,effect_provenance_matched:true,old_record_count:old.evidence?.length ?? 0,
    changed_payload:changed.code,stale_fence:stale.code,observation_verified:observations.result.kind,
    replayed:replay.value.replayed,additional_apply:'idle',
    ...(lifecycle?{control_state:lifecycle.controlState(),...lifecycle.counts(),expired_recovery_without_provider:true}:{} )},null,2));
} finally {
  await lifecycle?.service.close();
  await secondTransport?.close();
  await transport?.close();
  if (database) await closeMemoryDatabase(database);
  release(root);
  rmSync(root,{recursive:true,force:true});
}
