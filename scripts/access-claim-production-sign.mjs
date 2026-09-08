// Actual JARVIS issuer with an isolated authority DB; scope source remains a fixture.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
const build = process.argv[2];
const moduleAt = name => import(pathToFileURL(join(build, name)).href);
const { memoryDatabase, closeMemoryDatabase } = await moduleAt('tests/fixtures/memory-candidate-store.js');
const { memoryReadFenceFixture } = await moduleAt('tests/fixtures/memory-read-fence.js');
const { createProductionMemoryAccessClaim } = await moduleAt('src/memory-access-claim-production.js');
const body = JSON.parse(readFileSync(0, 'utf8'));
const db = await memoryDatabase();
try {
  const { config } = memoryReadFenceFixture(db, '2026-09-10T00:00:00.000Z', {
    provider_instance_id: body.provider_instance_id, signing_key_id: body.signing_key_id,
  });
  const issue = createProductionMemoryAccessClaim(db.authority, config, () => ({
    principal_id: body.principal_id, agent_id: body.agent_id, session_id: body.session_id,
    projects: body.projects, policy_revision: body.policy_revision, valid_until: body.expires_at,
  }));
  const result = issue(body.request ?? { method: 'sb_read_page', arguments: { id: body.page_id } }, new Date(body.issued_at));
  process.stdout.write(JSON.stringify(result));
} finally { closeMemoryDatabase(db); }
