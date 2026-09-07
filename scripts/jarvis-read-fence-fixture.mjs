// Synthetic V2 deletion through the real provider, followed by production reads.
// This probes read-fence configuration, not the complete JARVIS deletion UI.
import assert from 'node:assert/strict';

export async function prepareReadFenceDeletion({load, fixture, transport, provider, now}) {
  const {memoryReadFenceFixture} = await load('tests/fixtures/memory-read-fence.js');
  const {createProductionMemoryOutbox} = await load('src/memory-outbox-production.js');
  const {SecondBrainEffectService} = await load('src/second-brain-effect-service.js');
  const {MemoryTombstoneChain} = await load('src/memory-tombstone-chain.js');
  const {createMemoryEffectWriteRequest,memoryEffectDigest} = await load('src/second-brain-effect-v2.js');
  const {key,config} = memoryReadFenceFixture(fixture.database);
  // Environment is local to this opt-in probe process. Nothing is persisted to production.
  process.env.JARVIS_MEMORY_PROVIDER_INSTANCE_ID = config.provider_instance_id;
  process.env.JARVIS_MEMORY_SIGNING_KEY_ID = config.signing_key_id;
  process.env.JARVIS_MEMORY_PRIVATE_KEY_PATH = config.private_key_path;
  const runtime = createProductionMemoryOutbox(fixture.database.authority,{transport,clock:()=>now});
  const effects = new SecondBrainEffectService({authority:fixture.database.authority,transport,clock:()=>now,
    writer:{write:async()=>{throw new Error('fixture does not use an implicit effect writer');}},
    provider_instance_id:config.provider_instance_id,signing_key_id:config.signing_key_id,private_key:key});
  assert.equal(provider('seed').state,'proved');
  const seeded = await runtime.reader.search('ExampleAlpha');
  assert.equal(seeded.kind,'current');
  const record = seeded.evidence.find(item=>item.record)?.record;
  assert(record, 'seed memory must have a generation-bound record');
  const resolved = await effects.resolveTarget({record_id:record.record_id,record_digest:record.record_digest,
    generation_id:record.generation.generation_id,generation_manifest_digest:record.generation.generation_manifest_digest});
  assert.equal(resolved.kind,'data');
  const target = resolved.value;
  const targets = [target];
  const scope = {format:'none',sensitivity_classes:[target.sensitivity],valid_from:target.valid_from,
    valid_until:target.valid_until,max_records:1,max_bytes:4096,source_owner_classes:[target.source_owner_class]};
  const targetDigest = memoryEffectDigest('target_manifest',{targets});
  const scopeDigest = memoryEffectDigest('target_scope',{target_digests:[target.target_digest],scope});
  const payload = {disposition:'owner_requested',erasure_claim:'managed_erasure',external_receipts:[]};
  const laneId = `memdel:req:v1:${'a'.repeat(64)}`;
  const staleFence = effects.readFence('memory_read',now);
  const chain = new MemoryTombstoneChain(fixture.database.authority,Buffer.alloc(32,11));
  const appended = chain.append({operation:'forget',lane_id:laneId,targets,target_manifest_digest:targetDigest,
    scope_digest:scopeDigest,authority_receipt_digest:`sha256:${'c'.repeat(64)}`,
    payload_digest:memoryEffectDigest('effect_payload',payload),effective_at:now.toISOString()});
  const prior = Object.fromEntries(['provider_instance_id','generation_id','generation_manifest_digest','vault_head',
    'vault_tree','page_blob_oid','page_content_digest','citation_identity_full'].map(name=>[name,target[name]]));
  const request = createMemoryEffectWriteRequest({schema_version:2,kind:'memory_effect',provider_instance_id:config.provider_instance_id,
    lane:'deletion',lane_id:laneId,operation:'forget',target_manifest_digest:targetDigest,targets,scope,scope_digest:scopeDigest,
    expected_prior:prior,tombstone_high_water:appended.high_water,tombstone_chain_delta:[appended.entry],
    created_at:now.toISOString(),expires_at:new Date(now.getTime()+600000).toISOString(),payload},
  {principal_id:'principal:owner',signing_key_id:config.signing_key_id,not_before:now.toISOString(),nonce:'fixture-delete-nonce'},key);
  const accepted = await transport.call('sb_write_request',{request});
  assert.equal(accepted.kind,'data'); assert.equal(accepted.value.state,'pending');
  const applied = provider('apply'); assert.equal(applied.state,'proved');
  const unfenced = await transport.call('sb_read_page',{id:target.page_id});
  const stale = await transport.call('sb_read_page',{id:target.page_id,read_fence:staleFence});
  assert.deepEqual(unfenced,{kind:'error',code:'TOMBSTONE_FENCE_REQUIRED'});
  assert.deepEqual(stale,{kind:'error',code:'TOMBSTONE_SET_STALE'});
  const after = await runtime.reader.readPage(target.page_id);
  assert(['current','no_data'].includes(after.kind), JSON.stringify(after));
  assert.equal(after.evidence?.length ?? 0,0);
  await runtime.close();
  return {statusFence:()=>effects.readFence('memory_status',now), result:{deletion_state:applied.state,
    tombstone_sequence:appended.high_water.sequence,unfenced:unfenced.code,stale_fence:stale.code,
    deleted_page:after.kind,deleted_evidence_count:after.evidence?.length ?? 0}};
}
