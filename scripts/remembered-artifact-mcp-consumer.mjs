import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const moduleAt = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const profile = input.profile ?? 'scoped-record-read-v2';
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
    policy_revision: 'policy:fixture', valid_from: at.toISOString(), valid_until: until,
    sessions: [{ agent_id: 'agent:reader', session_id: 'session:reader', projects: ['project:shared-memory'], methods: ['sb_generation_status', 'sb_read_page'] }] };
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolve = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, () => ({
    principal_id: 'principal:owner', agent_id: 'agent:reader', session_id: 'session:reader', expires_at: until }));
  const monitored = { call: async (...args) => { const result = await transport.call(...args); if (result.kind !== 'data') console.error(JSON.stringify({ result, diagnostics: transport.diagnostics() })); return result; }, restart: () => transport.restart(), close: () => transport.close(), diagnostics: () => transport.diagnostics() };
  let client;
  if (profile === 'scoped-record-read-v3') {
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
  const first = await client.readRememberedArtifact(input.request, input.accepted);
  assert.equal(first.kind, profile === 'scoped-record-read-v3' ? 'remembered_artifact_observed' : 'remembered_content_observed');
  if (profile === 'scoped-record-read-v3') { assert.equal(first.access.sources.length, 1); assert.deepEqual(first.access.sources[0].classification.projects, ['project:shared-memory']); } assert.equal(first.record_ids.length, 4);
  await transport.restart();
  const restarted = await client.readRememberedArtifact(input.request, input.accepted);
  assert.deepEqual(restarted, first);
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [{ ...policy.sessions[0], projects: ['project:other', 'project:shared-memory'] }] }));
  const broader = await client.readRememberedArtifact(input.request, input.accepted);
  assert.deepEqual(broader, first);
  const original = readFileSync(input.config, 'utf8');
  writeFileSync(input.config, original.replace('policy:fixture', 'policy:revoked'));
  await assert.rejects(client.readRememberedArtifact(input.request, input.accepted));
  writeFileSync(input.config, original);
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
  await assert.rejects(client.readRememberedArtifact(input.request, input.accepted));
  console.log(JSON.stringify({ fixture: true, profile, production_composition: profile === "scoped-record-read-v3", internal_write_authority_fixture: true, supervised_stdio: true,
    read_after_restart: true, broader_authenticated_scope_allowed: true, provider_policy_change_rejected: true, issuer_policy_withdrawal_rejected: true,
    observation: first, automatic_settlement: false }, null, 2));
} finally { await transport.close(); closeMemoryDatabase(db); }
