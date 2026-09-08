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
  let currentCookie;
  let initialCookie;
  let sessionSource = () => ({ principal_id: body.principal_id, agent_id: body.agent_id,
    session_id: body.session_id, expires_at: body.expires_at });
  if (body.transport) {
    const { createPhoneGatewaySessionStore, PHONE_COOKIE_NAME } = await moduleAt('src/dashboard/phone-session.js');
    const { createPhoneMemorySessionSource } = await moduleAt('src/dashboard/memory-session-source.js');
    const now = () => Date.parse(body.issued_at);
    const owner = Buffer.alloc(32, 7);
    const sessions = createPhoneGatewaySessionStore({ key: Buffer.alloc(32, 8), now });
    const session = sessions.issue(owner);
    if (session.kind !== 'issued') throw new Error('session fixture unavailable');
    initialCookie = currentCookie = `${PHONE_COOKIE_NAME}=${session.cookieId}`;
    sessionSource = createPhoneMemorySessionSource({ sessions, cookieHeader: () => currentCookie,
      currentOwnerDigest: () => owner, agentId: body.agent_id, now });
    const authenticated = sessionSource();
    if (!authenticated) throw new Error('session authentication failed');
    const providerConfig = join(db.root, 'scoped-provider.toml');
    const original = readFileSync(body.transport.config, 'utf8');
    const marker = `session = "${body.session_id}"`;
    if (!original.includes(marker)) throw new Error('provider session fixture mismatch');
    writeFileSync(providerConfig, original.replace(marker, `session = "${authenticated.session_id}"`), { mode: 0o600 });
    body.transport.config = providerConfig;
    body.session_id = authenticated.session_id;
  }
  const policyPath = join(db.root, 'read-policy.json');
  const policy = { schema_version: 1, provider_instance_id: body.provider_instance_id,
    principal_id: body.principal_id, policy_revision: body.policy_revision,
    valid_from: body.issued_at, valid_until: body.expires_at,
    sessions: [{ agent_id: body.agent_id, session_id: body.session_id, projects: body.projects,
      methods: ['sb_read_page', 'sb_search'] }] };
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolve = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, sessionSource);
  const issue = createProductionMemoryAccessClaim(db.authority, config, resolve);
  if (body.transport) {
    const { createMemoryScopedClient } = await moduleAt('src/memory-scoped-client.js');
    const { createSecondBrainTransport } = await moduleAt('src/second-brain-transport.js');
    const transport = createSecondBrainTransport({ contractProfile: 'scoped-record-read-v1',
      launcherPath: body.transport.launcher, configPath: body.transport.config, contractPath: body.transport.contract });
    let withdrawAfterResponse = false;
    const client = createMemoryScopedClient({ issue, now: () => new Date(body.issued_at),
      transport: { call: async (...args) => {
        const outcome = await transport.call(...args);
        if (withdrawAfterResponse) writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
        return outcome;
      }, restart: () => transport.restart(), close: () => transport.close(), diagnostics: () => transport.diagnostics() },
      budgets: { max_hits: 50, max_excerpt_bytes: 8192, max_total_bytes: 1000000, max_page_bytes: 100000 },
      max_age_ms: 86400000, expiry_ms: 172800000 });
    try {
      const page = await client.readPage(body.page_id);
      const search = await client.search('Cited', 2);
      currentCookie = undefined;
      let missingCookieDenied = false;
      try { await client.search('Cited', 2); }
      catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; missingCookieDenied = true; }
      if (!missingCookieDenied) throw new Error('missing cookie accepted');
      currentCookie = initialCookie;
      withdrawAfterResponse = true;
      let denied = false;
      try { await client.search('Cited', 2); }
      catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; denied = true; }
      if (!denied || page.pages.length !== 1 || search.pages.length !== 1) throw new Error('scoped client acceptance failed');
      process.stdout.write(JSON.stringify({ page_groups: page.pages.length, search_groups: search.pages.length,
        policy_withdrawn_after_actual_response_denied: denied,
        phone_session_store_authenticated: true, missing_cookie_denied: missingCookieDenied }));
    } finally { await transport.close(); }
  } else {
  const result = issue(body.request ?? { method: 'sb_read_page', arguments: { id: body.page_id } }, new Date(body.issued_at));
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
  let denied = false;
  try { issue(body.request ?? { method: 'sb_read_page', arguments: { id: body.page_id } }, new Date(body.issued_at)); }
  catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; denied = true; }
  if (!denied) throw new Error('policy withdrawal was ignored');
  process.stdout.write(JSON.stringify(result));
  }
} finally { closeMemoryDatabase(db); }
