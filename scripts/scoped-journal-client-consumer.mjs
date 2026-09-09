import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const load = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const { memoryDatabase, closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
const { memoryReadFenceFixture } = await load('tests/fixtures/memory-read-fence.js');
const { createProductionMemoryAccessClaim } = await load('src/memory-access-claim-production.js');
const { createFileMemoryAccessScopeResolver } = await load('src/memory-access-policy.js');
const { createMemoryScopedJournalClient } = await load('src/memory-scoped-journal-client.js');
const { createSecondBrainTransport } = await load('src/second-brain-transport.js');
const db = await memoryDatabase();
const transport = createSecondBrainTransport({ contractProfile: 'scoped-request-status-v1',
  launcherPath: input.launcher, configPath: input.config, contractPath: input.contract });
try {
  const { config } = memoryReadFenceFixture(db);
  const scope = input.request.preparation.binding.identity;
  const at = new Date('2026-08-31T03:30:00.000Z'), until = '2026-08-31T03:40:00.000Z';
  const policyPath = join(db.root, 'policy.json');
  const policy = { schema_version: 3, provider_instance_id: 'provider:fixture', principal_id: 'principal:owner',
    policy_revision: scope.policy_revision, valid_from: at.toISOString(), valid_until: until,
    agents: [{ agent_id: 'agent:reader', projects: scope.projects, methods: ['sb_request_status'] }] };
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolver = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, () => ({
    principal_id: 'principal:owner', agent_id: 'agent:reader', session_id: 'session:reader', expires_at: until }));
  const client = createMemoryScopedJournalClient({ transport,
    issue: createProductionMemoryAccessClaim(db.authority, config, resolver, 'memory_status'), now: () => at,
    budgets: { max_hits: 1, max_excerpt_bytes: 8192, max_total_bytes: 100000, max_page_bytes: 100000 } });
  const first = await client.recoverRequestStatus(input.request);
  assert.equal(first.kind, 'scoped_journal_status_observed');
  assert.equal(first.status.state, input.expected_state);
  assert.equal(first.status.acceptance.replayed, true);
  assert.equal(first.status.acceptance.request_digest, input.request.request_digest);
  assert.equal('generation' in first, false);
  await transport.restart();
  assert.deepEqual(await client.recoverRequestStatus(input.request), first);
  const original = readFileSync(input.config, 'utf8');
  writeFileSync(input.config, original.replace('jarvis_public_keys =', 'revoked_jarvis_signing_key_ids = ["jarvis:fixture"]\njarvis_public_keys ='));
  await assert.rejects(client.recoverRequestStatus(input.request));
  writeFileSync(input.config, original);
  assert.deepEqual(await client.recoverRequestStatus(input.request), first);
  writeFileSync(policyPath, JSON.stringify({ ...policy, agents: [] }));
  await assert.rejects(client.recoverRequestStatus(input.request));
  let recovered;
  if (input.recovery) {
    writeFileSync(policyPath, JSON.stringify(policy));
    const { AuthorityDb } = await load('src/db.js');
    const { recoverMemoryScopedJournalAcceptance } = await load('src/memory-scoped-journal-recovery.js');
    const authority = new AuthorityDb(input.recovery.database);
    try {
      const options = { authority, spoolRoot: input.recovery.spoolRoot, providerInstanceId: 'provider:fixture' };
      if (input.recovery.cli) {
        const { execute } = await load('src/cli.js');
        memoryReadFenceFixture({ ...db, authority });
        const response = await execute(['memory', 'reconcile-scoped', input.recovery.lease.outbox_id,
          '--once', '--db', input.recovery.database], { clock: () => at,
          scopedMemoryReconcileOptions: { policy_path: policyPath, read_fence_config: config,
            spool_root: input.recovery.spoolRoot, roots: {},
            authenticated_session: () => ({ principal_id: 'principal:owner', agent_id: 'agent:reader', session_id: 'session:reader', expires_at: until }),
            journal_transport_options: { launcherPath: input.launcher, configPath: input.config, contractPath: input.contract },
            completion_transport_options: { launcherPath: input.launcher, configPath: input.config,
              contractPath: input.contract.replace('scoped-status-v1', 'scoped-read-v5') } } });
        assert.equal(response.command, 'memory.reconcile-scoped');
        assert.equal(response.result.kind, 'scoped_reconciliation_deferred');
        recovered = response.result.recovery;
      } else if (input.recovery.once) {
        const { reconcileMemoryScopedOnce } = await load('src/memory-scoped-reconcile-once.js');
        const result = await reconcileMemoryScopedOnce({ ...options, journal: client, clock: () => at, roots: {},
          completion: { withRememberedCompletion: () => { throw Error('pending/failed must not read artifacts'); } } },
          input.recovery.lease.outbox_id, 'worker:once', 10000);
        assert.equal(result.kind, 'scoped_reconciliation_deferred');
        assert.equal(result.observed_provider_state, input.expected_state);
        recovered = result.recovery;
      } else recovered = await recoverMemoryScopedJournalAcceptance(options, input.recovery.lease, client, () => at);
      assert.equal(recovered.kind, 'scoped_journal_acceptance_recovered');
      assert.equal(recovered.acceptance.replayed, !input.recovery.crash_after_commit);
    } finally { authority.close(); }
    if (input.recovery.crash_after_commit) {
      await transport.close(); closeMemoryDatabase(db);
      process.exit(73);
    }
  }
  console.log(JSON.stringify({ state: first.status.state, original_acceptance_recovered: true,
    restarted_equal: true, provider_revocation_denied: true, issuer_revocation_denied: true,
    current_artifact_claimed: false, request_id: first.status.request_id,
    ...(recovered ? { recovered, commit_exit: 73, once: Boolean(input.recovery.once), cli: Boolean(input.recovery.cli) } : {}) }));
} finally { await transport.close(); closeMemoryDatabase(db); }
