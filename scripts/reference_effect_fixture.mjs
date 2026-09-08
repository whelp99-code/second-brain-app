// Isolated signed-owner fixture. Uses the existing JARVIS effect and SB request paths.
// This is not the user confirmation UI or a product session delivery implementation.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash, createPublicKey} from 'node:crypto';
import {join} from 'node:path';

export async function referenceEffectFixture({load, database, key, config, launcher, root, sb, python}) {
  const {createSecondBrainTransport} = await load('src/index.js');
  const {SecondBrainEffectService} = await load('src/second-brain-effect-service.js');
  const {MemoryTombstoneChain} = await load('src/memory-tombstone-chain.js');
  const {createMemoryEffectWriteRequest, memoryEffectDigest} = await load('src/second-brain-effect-v2.js');
  const {MEMORY_EFFECT_LANE_PREFIX} = await load('src/second-brain-effect-v2-contract.js');
  const {verifyMemoryDispositionProof} = await load('src/memory-disposition-proof.js');
  const {parseMemoryLifecycleObservationManifest} = await load('src/memory-lifecycle-observation-manifest.js');
  const now = new Date();
  const publicKey = createPublicKey(key).export({format:'pem',type:'spki'}).toString();
  database.authority.db.prepare(`INSERT INTO memory_provider_proof_keys VALUES
    (?, ?, ?, 'Ed25519', ?, ?, 'active', ?, ?, ?)`)
    .run('provider:key',config.provider_instance_id,'a'.repeat(40),publicKey,
      createHash('sha256').update(publicKey).digest('hex'), now.toISOString(),
      new Date(now.getTime()+86400000).toISOString(),now.toISOString());
  const transport = createSecondBrainTransport({launcherPath:launcher,configPath:join(root,'config.toml')});
  const service = new SecondBrainEffectService({authority:database.authority,transport,clock:()=>new Date(),
    writer:{write:async()=>{throw new Error('no implicit writer');}},
    provider_instance_id:config.provider_instance_id,signing_key_id:config.signing_key_id,private_key:key});
  const chain = new MemoryTombstoneChain(database.authority,Buffer.alloc(32,11));
  return {close:()=>transport.close(), async apply(operation, record, content) {
    assert(['correct','forget'].includes(operation));
    const resolved = await service.resolveTarget({record_id:record.record_id,record_digest:record.record_digest,
      generation_id:record.generation.generation_id,generation_manifest_digest:record.generation.generation_manifest_digest});
    assert.equal(resolved.kind,'data',JSON.stringify(resolved));
    const target = resolved.value; const targets = [target];
    const scope = {format:'none',sensitivity_classes:[target.sensitivity],valid_from:target.valid_from,
      valid_until:target.valid_until,max_records:1,max_bytes:4096,source_owner_classes:[target.source_owner_class]};
    const targetDigest = memoryEffectDigest('target_manifest',{targets});
    const scopeDigest = memoryEffectDigest('target_scope',{target_digests:[target.target_digest],scope});
    const payload = operation==='correct'
      ? {content,content_digest:memoryEffectDigest('effect_content',{content}),content_bytes:Buffer.byteLength(content),disposition:'superseded'}
      : {disposition:'owner_requested',erasure_claim:'provider_local_suppression',external_receipts:[]};
    const lane = operation==='correct'?'correction':'deletion';
    const laneId = MEMORY_EFFECT_LANE_PREFIX[lane]+targetDigest.slice(7);
    const at = new Date();
    const appended = chain.append({operation,lane_id:laneId,targets,target_manifest_digest:targetDigest,
      scope_digest:scopeDigest,authority_receipt_digest:`sha256:${'c'.repeat(64)}`,
      payload_digest:memoryEffectDigest('effect_payload',payload),effective_at:at.toISOString()});
    const expectedPrior = Object.fromEntries(['provider_instance_id','generation_id','generation_manifest_digest',
      'vault_head','vault_tree','page_blob_oid','page_content_digest','citation_identity_full'].map(name=>[name,target[name]]));
    const request = createMemoryEffectWriteRequest({schema_version:2,kind:'memory_effect',
      provider_instance_id:config.provider_instance_id,lane,lane_id:laneId,operation,
      target_manifest_digest:targetDigest,targets,scope,scope_digest:scopeDigest,expected_prior:expectedPrior,
      tombstone_high_water:appended.high_water,tombstone_chain_delta:[appended.entry],
      created_at:at.toISOString(),expires_at:new Date(at.getTime()+600000).toISOString(),payload},
    {principal_id:'principal:owner',signing_key_id:config.signing_key_id,not_before:at.toISOString(),nonce:laneId},key);
    const accepted = await transport.call('sb_write_request',{request});
    assert.equal(accepted.kind,'data',JSON.stringify(accepted));
    assert.equal(accepted.value.state,'pending');
    const applied = JSON.parse(execFileSync(python,
      ['-m','tests.fixtures.jarvis_memory_provider','apply',root,'--live-clock'],{cwd:sb,encoding:'utf8',timeout:120000}));
    assert.equal(applied.state,'proved',JSON.stringify(applied));
    const status = await service.requestStatus(request.request_id);
    assert.equal(status.kind,'data',JSON.stringify(status));
    assert.equal(status.value.state,'proved');
    const proof = verifyMemoryDispositionProof(database.authority,status.value.proof,{
      ...request,delegation_id:request.delegation.delegation_id,delegation_digest:request.delegation.delegation_digest,
      payload_digest:request.delegation.payload_digest,tombstone_sequence:appended.high_water.sequence,
      tombstone_set_root:appended.high_water.set_root},new Date());
    const observed = parseMemoryLifecycleObservationManifest(status.value.observations,proof);
    return {request_id:request.request_id,provider_state:applied.state,proof_id:proof.proof_id,
      observation_kind:observed.result.kind,tombstone_sequence:appended.high_water.sequence};
  }};
}
