import assert from 'node:assert/strict';
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { execFileSync } from 'node:child_process';

export async function dispatchAfterCancellation(input, f, moduleAt) {
  const worker = mode => JSON.parse(execFileSync(input.python,
    [`${input.sb_root}/scripts/cancellation-dispatch-provider.py`, input.work, mode],
    { encoding: 'utf8', cwd: input.sb_root, env: { ...process.env, TMPDIR: '/var/tmp' }, timeout: 60000 }));
  const prepared = worker('prepare');
  const { createSecondBrainTransport } = await moduleAt('src/second-brain-transport');
  const { createSecondBrainWriteRequestAdapter } = await moduleAt('src/second-brain-write-adapter');
  const { SecondBrainEffectService } = await moduleAt('src/second-brain-effect-service');
  const { registerMemoryEffectDelegationKey, registerMemoryProviderProofKey } = await moduleAt('src/memory-effect-delegation');
  const { dispatchFollowupCorrection } = await moduleAt('tests/fixtures/memory-followup-correction');
  const { notProvedMemoryObserver, unreachableMemoryCompactor } = await moduleAt('tests/fixtures/memory-lifecycle-runtime');
  const key = createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),
    Buffer.from(Array.from({length:32}, (_, i) => i + 32))]), format:'der',type:'pkcs8' });
  const { ProductionMemoryLifecycleObserver } = await moduleAt('src/memory-lifecycle-observer');
  const { SecondBrainStatusObservationSource } = await moduleAt('src/second-brain-lifecycle-observations');
  const clock = () => new Date();
  const now = clock();
  registerMemoryEffectDelegationKey(f.db, { key_id:'jarvis:followup', principal_id:'principal:owner',
    public_key_pem:createPublicKey(key).export({format:'pem',type:'spki'}).toString(),
    valid_from:now.toISOString(), valid_until:new Date(now.getTime()+600000).toISOString() }, now);
  registerMemoryProviderProofKey(f.db, { key_id:'provider:followup', provider_instance_id:'provider:fixture',
    provider_release_sha:'a'.repeat(40), public_key_pem:prepared.proof_public_key,
    valid_from:now.toISOString(), valid_until:new Date(now.getTime()+600000).toISOString() }, now);
  const transport = createSecondBrainTransport({ launcherPath:prepared.launcher, configPath:prepared.config,
    contractPath:`${input.sb_root}/contracts/second-brain-mcp-v3.json`, contractProfile:'remember-schema5' });
  let calls = 0; let emitted;
  const adapter = createSecondBrainWriteRequestAdapter(transport, f.db, clock);
  const writer = { write: async value => { calls++; emitted = value; return adapter.write(value); } };
  const provider = new SecondBrainEffectService({ authority:f.db, transport, writer, clock,
    provider_instance_id:'provider:fixture', signing_key_id:'jarvis:followup', private_key:key });
  try {
    const page = await transport.call('sb_read_page', { id:prepared.selector.page_id,
      read_fence:provider.readFence('memory_read') });
    assert.equal(page.kind, 'data', JSON.stringify(page));
    const records = page.value.records.filter(row => row.record_text === prepared.selector.exact_record);
    assert.equal(records.length, 1, JSON.stringify(page.value));
    const resolved = await provider.resolveTarget({ record_id:records[0].record_id,
      record_digest:records[0].record_digest, generation_id:page.value.generation_id,
      generation_manifest_digest:page.value.generation_manifest_digest });
    assert.equal(resolved.kind, 'data', JSON.stringify(resolved));
    const target = resolved.value;
    const scope = { format:'none', sensitivity_classes:['personal'], valid_from:target.valid_from,
      valid_until:target.valid_until, max_records:1, max_bytes:4096, source_owner_classes:['provider_owned'] };
    const followup = await dispatchFollowupCorrection(f.db, { ...f.runtime, clock, writer, provider,
      signing_key_id:'jarvis:followup', private_key:key, observer:notProvedMemoryObserver,
      compactor:unreachableMemoryCompactor }, target, scope, 'IndependentBeta corrected 최신기억', 'actual-followup');
    assert.equal(followup.record.state, 'reconciling', JSON.stringify(followup.record));
    assert.equal(calls, 1);
    assert.equal(emitted.tombstone_chain_delta.length, 1);
    const prior = f.db.db.prepare('SELECT tombstone_set_root FROM memory_cancellation_settlements WHERE correction_id=?').get(f.record.correction_id);
    assert.equal(emitted.tombstone_chain_delta[0].sequence, 2);
    assert.equal(emitted.tombstone_chain_delta[0].previous_root, prior.tombstone_set_root);
    assert.equal(followup.record.tombstone_sequence, 2);
    const cursor = f.db.db.prepare('SELECT active_lane_id,accepted_through_sequence FROM memory_effect_dispatch_cursor').get();
    assert.deepEqual(cursor, {active_lane_id:null,accepted_through_sequence:2});
    const applied = worker('apply');
    assert.equal(applied.request_id, followup.record.request_id);
    assert.equal(applied.tombstone_set_root, emitted.tombstone_high_water.set_root);
    const status = await provider.requestStatus(applied.request_id);
    assert.equal(status.kind, 'data', JSON.stringify(status));
    assert.equal(status.value.state, 'proved', JSON.stringify(status));
    await transport.restart();
    const replay = await provider.requestStatus(applied.request_id);
    assert.deepEqual(replay, status);
    const observer = new ProductionMemoryLifecycleObserver({ authority:f.db, provider,
      observations:new SecondBrainStatusObservationSource(provider), clock });
    const observation = await observer.correction(followup.record);
    assert.equal(observation.kind, 'correction', JSON.stringify(observation));
    const reconciled = await followup.saga.reconcile(followup.record.correction_id);
    assert.equal(reconciled.state, 'reconciling');
    assert.equal(calls, 1);
    const { AuthorityDatabaseRuntime } = await moduleAt('src/authority-database-runtime');
    const { MemoryAuthorityCompactor } = await moduleAt('src/memory-authority-compactor');
    const { MemoryManagedSurfaceScanner } = await moduleAt('src/memory-managed-surface-scanner');
    const { MemoryCorrectionSaga } = await moduleAt('src/memory-correction-saga');
    await f.databaseRuntime.close();
    f.db.reopen();
    const databaseRuntime = new AuthorityDatabaseRuntime(f.db, { registry_root:`${f.root}/registry`, watchdog_ms:5000 });
    let settled;
    try {
      const layout = { spool_root:f.runtime.spool_root, state_root:`${f.root}/state`, dist_root:`${f.root}/dist`,
        backup_root:`${f.root}/backups`, restore_root:`${f.root}/restore` };
      const compactor = new MemoryAuthorityCompactor({ runtime:databaseRuntime, layout,
        scanner:new MemoryManagedSurfaceScanner({ authority:f.db, layout }), clock });
      const saga = new MemoryCorrectionSaga({ ...f.runtime, clock, writer, provider, observer, compactor,
        signing_key_id:'jarvis:followup', private_key:key });
      settled = await saga.reconcile(followup.record.correction_id);
      assert.equal(settled.state, 'settled', JSON.stringify(settled));
      assert.deepEqual(await saga.reconcile(followup.record.correction_id), settled);
    } finally { await databaseRuntime.close(); f.db.reopen(); }
    assert.equal(calls, 1);
    assert.equal(f.writer.calls.length, 0);
    const recovered = JSON.parse(execFileSync(process.execPath, [`${input.sb_root}/scripts/cancellation-settled-replay.mjs`],
      { encoding:'utf8', input:JSON.stringify({ build:input.build, database:f.database.path,
        spool_root:f.runtime.spool_root, correction_id:settled.correction_id }), timeout:30000 }));
    assert.deepEqual(recovered.record, settled);
    assert.deepEqual(recovered.command, {state:'completed'});
    assert.deepEqual(recovered.catalog, {expected_surface_count:70,observed_surface_count:70,
      omission_count:0,error_count:0,match_count:0});
    return { node_pid:process.pid, correction_id:followup.record.correction_id,
      request_id:followup.record.request_id, dispatch_calls:calls, delta_length:emitted.tombstone_chain_delta.length, previous_root_matches:true,
      status_replay_after_restart:true, incomplete_observation_held:true,
      verified_proof_digest:observation.proof.proof_digest,
      provider_surface_count:observation.provider_inventory.observed_surface_count,
      reingress_guard_count:observation.reingress_guards.observed_guard_count, cursor, provider:applied,
      mcp_status:status.value.state, jarvis_state:settled.state,
      settlement_replay_pid:recovered.pid, settlement_exact_replay:true,
      command_state:recovered.command.state, surface_catalog:recovered.catalog,
      scope:'same JARVIS DB command approval and real MCP target/status/write; actual provider execution; real proof/40 surfaces/10 guards and local compaction/settlement' };
  } finally { await transport.close(); }
}
