import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const moduleAt = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const profile = input.profile ?? 'scoped-record-read-v2';
const requestScope = input.request.preparation.binding.identity;
let accepted = input.accepted;
const { memoryDatabase, closeMemoryDatabase } = await moduleAt('tests/fixtures/memory-candidate-store.js');
const { memoryReadFenceFixture } = await moduleAt('tests/fixtures/memory-read-fence.js');
const { createProductionMemoryAccessClaim } = await moduleAt('src/memory-access-claim-production.js');
const { createMemoryScopedClient } = await moduleAt('src/memory-scoped-client.js');
const { createSecondBrainTransport } = await moduleAt('src/second-brain-transport.js');
const { createFileMemoryAccessScopeResolver } = await moduleAt('src/memory-access-policy.js');
const db = await memoryDatabase();
const transport = createSecondBrainTransport({ contractProfile: profile,
  launcherPath: input.launcher, configPath: input.config, contractPath: input.contract });
try {
  const { config } = memoryReadFenceFixture(db);
  const at = new Date('2026-08-31T03:30:00.000Z');
  const until = '2026-08-31T03:40:00.000Z';
  const policyPath = join(db.root, 'artifact-policy.json');
  const policy = { schema_version: 1, provider_instance_id: 'provider:fixture', principal_id: 'principal:owner',
    policy_revision: requestScope.policy_revision, valid_from: at.toISOString(), valid_until: until,
    sessions: [{ agent_id: 'agent:reader', session_id: 'session:reader', projects: requestScope.projects, methods: ['sb_generation_status', 'sb_read_page'] }] };
  if ((profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5')) {
    policy.schema_version = 3;
    policy.agents = policy.sessions.map(({ session_id, ...row }) => ({ ...row,
      methods: ['sb_generation_status', 'sb_read_page', 'sb_request_status'] }));
    delete policy.sessions;
  }
  const rows = (profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5') ? 'agents' : 'sessions';
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolve = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, () => ({
    principal_id: 'principal:owner', agent_id: 'agent:reader', session_id: 'session:reader', expires_at: until }));
  let cancellationProbe;
  const cancellationChecks = [];
  const monitored = { call: async (...args) => { const result = await transport.call(...args); if (cancellationProbe && ++cancellationProbe.calls === cancellationProbe.after) cancellationProbe.controller.abort(); if (result.kind !== 'data') console.error(JSON.stringify({ result, diagnostics: transport.diagnostics() })); return result; }, restart: () => transport.restart(), close: () => transport.close(), diagnostics: () => transport.diagnostics() };
  let client;
  if ((profile === 'scoped-record-read-v3' || (profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5'))) {
    const { createProductionScopedMemory } = await moduleAt('src/memory-scoped-production.js');
    const projectionKey = join(db.root, 'projection.key');
    writeFileSync(projectionKey, Buffer.alloc(32, 7), { mode: 0o600 });
    const production = createProductionScopedMemory(db.authority, { profile, policy_path: policyPath,
      projection_key_path: projectionKey, read_fence_config: config, clock: () => at, transport: monitored,
      authenticated_session: () => ({ principal_id: 'principal:owner', agent_id: 'agent:reader', session_id: 'session:reader', expires_at: until }) });
    client = production.client;
    assert.equal((await client.status()).generation.provider_instance_id, 'provider:fixture');
  } else {
    client = createMemoryScopedClient({ profile, transport: monitored,
      issue: createProductionMemoryAccessClaim(db.authority, config, resolve), now: () => at,
      budgets: { max_hits: 50, max_excerpt_bytes: 8192, max_total_bytes: 1000000, max_page_bytes: 100000 },
      max_age_ms: 86400000, expiry_ms: 172800000 });
  }
  if (profile === 'scoped-record-read-v5') {
    assert.equal(input.accepted, undefined);
    const recovered = await client.recoverRequestStatus(input.request);
    accepted = recovered.status.acceptance;
    assert.equal(accepted.replayed, true);
  }
  const first = await client.readRememberedArtifact(input.request, accepted);
  assert.equal(first.kind, (profile === 'scoped-record-read-v3' || (profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5')) ? 'remembered_artifact_observed' : 'remembered_content_observed');
  if ((profile === 'scoped-record-read-v3' || (profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5'))) { assert.equal(first.access.sources.length, 1); assert.deepEqual(first.access.sources[0].classification.projects, requestScope.projects); } assert.equal(input.custom_request ? first.record_ids.length > 0 : first.record_ids.length === 4, true);
  let combined, durableObservation;
  if (profile === 'scoped-record-read-v5') {
    combined = await client.readRememberedCompletion(input.request);
    assert.equal(combined.kind, 'remembered_completion_observed');
    assert.equal(combined.status.state, 'proved');
    assert.deepEqual(combined.artifact, first);
    // Abort after real MCP transport resolution, before the client consumes it.
    // The transport has already fulfilled and cannot reject this race itself.
    for (const after of [0, 1, 2, 3]) {
      cancellationProbe = { controller: new AbortController(), calls: 0, after };
      if (after === 0) cancellationProbe.controller.abort();
      await assert.rejects(client.readRememberedCompletion(input.request, cancellationProbe.controller.signal),
        { code: 'SECOND_BRAIN_CANCELLED' });
      assert.equal(cancellationProbe.calls, after);
      cancellationChecks.push({ after_responses: after, calls: cancellationProbe.calls, rejected: true });
      cancellationProbe = undefined;
    }
    assert.deepEqual(await client.readRememberedCompletion(input.request), combined);
    if (input.reconciliation) {
      const { AuthorityDb } = await moduleAt('src/db.js');
      const { observeMemoryScopedCompletion } = await moduleAt('src/memory-scoped-completion-observation.js');
      const authority = new AuthorityDb(input.reconciliation.database);
      try {
        const options = { authority, spoolRoot: input.reconciliation.spoolRoot, providerInstanceId: 'provider:fixture' };
        if (!input.reconciliation.once) {
          const recorded = await observeMemoryScopedCompletion(options, input.reconciliation.lease, client, () => at);
          assert.equal(recorded.replayed, false);
          durableObservation = await observeMemoryScopedCompletion(options, input.reconciliation.lease, client, () => at);
          assert.deepEqual(durableObservation, { ...recorded, replayed: true });
        }
        if (input.reconciliation.atomic) {
          let result;
          if (input.reconciliation.once) {
            const { reconcileMemoryScopedOnce } = await moduleAt('src/memory-scoped-reconcile-once.js');
            const { releaseMemoryScopedReconciliation } = await moduleAt('src/memory-scoped-reconciliation.js');
            const { createMemoryScopedJournalClient } = await moduleAt('src/memory-scoped-journal-client.js');
            const journalTransport = createSecondBrainTransport({ contractProfile: 'scoped-request-status-v1',
              launcherPath: input.launcher, configPath: input.config,
              contractPath: input.contract.replace('scoped-read-v5', 'scoped-status-v1') });
            try {
              const journal = createMemoryScopedJournalClient({ transport: journalTransport, now: () => at,
                issue: createProductionMemoryAccessClaim(db.authority, config, resolve, 'memory_status'),
                budgets: { max_hits: 1, max_excerpt_bytes: 8192, max_total_bytes: 100000, max_page_bytes: 100000 } });
              releaseMemoryScopedReconciliation(authority, input.reconciliation.lease, at);
              result = await reconcileMemoryScopedOnce({ ...options, journal, completion: client, clock: () => at,
                roots: input.reconciliation.roots }, input.reconciliation.lease.outbox_id, 'worker:once', 10000);
            } finally { await journalTransport.close(); }
          } else {
            const { settleMemoryScopedCompletion } = await moduleAt('src/memory-scoped-settlement.js');
            result = await settleMemoryScopedCompletion(options, input.reconciliation.lease, client, () => at, input.reconciliation.roots);
          }
          assert.equal(result.kind, 'memory_scoped_settled');
          assert.equal(result.replayed, false);
          // Abrupt exit after the complete DB transaction; the next process
          // must recover the committed receipt without another MCP write.
          authority.close();
          closeMemoryDatabase(db);
          process.exit(73);
        }

      } finally { authority.close(); }
    }


  }
  let completion;
  if ((profile === 'scoped-record-read-v4' || profile === 'scoped-record-read-v5')) {
    completion = await client.requestStatus(input.request, accepted);
    assert.equal(completion.status.state, 'proved');
    assert.equal(completion.status.proof.request_digest, input.request.request_digest);
  }
  await transport.restart();
  const restarted = await client.readRememberedArtifact(input.request, accepted);
  assert.deepEqual(restarted, first);
  if (combined) assert.deepEqual(await client.readRememberedCompletion(input.request), combined);
  if (profile === 'scoped-record-read-v5') assert.deepEqual((await client.recoverRequestStatus(input.request)).status.acceptance, accepted);
  if (completion) assert.deepEqual(await client.requestStatus(input.request, accepted), completion);
  writeFileSync(policyPath, JSON.stringify({ ...policy, [rows]: [{ ...policy[rows][0], projects: [...new Set(['project:other', ...requestScope.projects])].sort() }] }));
  const broader = await client.readRememberedArtifact(input.request, accepted);
  assert.deepEqual(broader, first);
  const original = readFileSync(input.config, 'utf8');
  writeFileSync(input.config, original.replace(requestScope.policy_revision, 'policy:revoked'));
  await assert.rejects(client.readRememberedArtifact(input.request, accepted));
  if (completion) await assert.rejects(client.requestStatus(input.request, accepted));
  if (profile === 'scoped-record-read-v5') await assert.rejects(client.recoverRequestStatus(input.request));
  if (combined) await assert.rejects(client.readRememberedCompletion(input.request));
  writeFileSync(input.config, original);
  writeFileSync(policyPath, JSON.stringify({ ...policy, [rows]: [] }));
  await assert.rejects(client.readRememberedArtifact(input.request, accepted));
  if (completion) await assert.rejects(client.requestStatus(input.request, accepted));
  if (profile === 'scoped-record-read-v5') await assert.rejects(client.recoverRequestStatus(input.request));
  if (combined) await assert.rejects(client.readRememberedCompletion(input.request));
  console.log(JSON.stringify({ durable_observation: durableObservation, cancellation_checks: cancellationChecks, combined_completion: combined, recovered_without_local_acceptance: profile === 'scoped-record-read-v5', completion, request_status_after_restart: !!completion, fixture: true, profile, production_composition: (profile === "scoped-record-read-v3" || (profile === "scoped-record-read-v4" || profile === "scoped-record-read-v5")), internal_write_authority_fixture: true, supervised_stdio: true,
    read_after_restart: true, broader_authenticated_scope_allowed: true, provider_policy_change_rejected: true, issuer_policy_withdrawal_rejected: true,
    observation: first, automatic_settlement: false }, null, 2));
} finally { await transport.close(); closeMemoryDatabase(db); }
