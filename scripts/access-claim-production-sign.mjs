// Actual JARVIS issuer with an isolated authority DB; scope source remains a fixture.
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
const build = process.argv[2];
const moduleAt = name => import(pathToFileURL(join(build, name)).href);
const { memoryDatabase, closeMemoryDatabase } = await moduleAt('tests/fixtures/memory-candidate-store.js');
const { memoryReadFenceFixture } = await moduleAt('tests/fixtures/memory-read-fence.js');
const { createProductionMemoryAccessClaim } = await moduleAt('src/memory-access-claim-production.js');
const { createFileMemoryAccessScopeResolver } = await moduleAt('src/memory-access-policy.js');
const body = JSON.parse(readFileSync(0, 'utf8'));
const db = await memoryDatabase();
try {
  const { config } = memoryReadFenceFixture(db, '2026-09-10T00:00:00.000Z', {
    provider_instance_id: body.provider_instance_id, signing_key_id: body.signing_key_id,
  });
  const policyPath = join(db.root, 'read-policy.json');
  const policy = { schema_version: 1, provider_instance_id: body.provider_instance_id,
    principal_id: body.principal_id, policy_revision: body.policy_revision,
    valid_from: body.issued_at, valid_until: body.expires_at,
    sessions: [{ agent_id: body.agent_id, session_id: body.session_id, projects: body.projects,
      methods: ['sb_read_page', 'sb_search'] }] };
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolve = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, () => ({
    principal_id: body.principal_id, agent_id: body.agent_id, session_id: body.session_id, expires_at: body.expires_at,
  }));
  const issue = createProductionMemoryAccessClaim(db.authority, config, resolve);
  const result = issue(body.request ?? { method: 'sb_read_page', arguments: { id: body.page_id } }, new Date(body.issued_at));
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
  let denied = false;
  try { issue(body.request ?? { method: 'sb_read_page', arguments: { id: body.page_id } }, new Date(body.issued_at)); }
  catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; denied = true; }
  if (!denied) throw new Error('policy withdrawal was ignored');
  process.stdout.write(JSON.stringify(result));
} finally { closeMemoryDatabase(db); }
