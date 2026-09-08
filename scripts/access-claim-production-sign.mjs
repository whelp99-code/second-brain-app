// Actual JARVIS issuer with an isolated authority DB; scope source remains a fixture.
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const build = process.argv[2];
const moduleAt = name => import(pathToFileURL(join(build, name)).href);
const { memoryDatabase, closeMemoryDatabase } = await moduleAt('tests/fixtures/memory-candidate-store.js');
const { memoryReadFenceFixture } = await moduleAt('tests/fixtures/memory-read-fence.js');
const { createProductionMemoryAccessClaim } = await moduleAt('src/memory-access-claim-production.js');
const { createFileMemoryAccessScopeResolver } = await moduleAt('src/memory-access-policy.js');
const body = JSON.parse(readFileSync(0, 'utf8'));
const profile = body.transport?.profile ?? "scoped-record-read-v1";
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
      methods: [...(profile === 'scoped-record-read-v2' ? ['sb_generation_status'] : []), 'sb_read_page', 'sb_search'] }] };
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  const resolve = createFileMemoryAccessScopeResolver(policyPath, config.provider_instance_id, sessionSource);
  const issue = createProductionMemoryAccessClaim(db.authority, config, resolve);
  if (body.transport) {
    const { createMemoryScopedClient } = await moduleAt('src/memory-scoped-client.js');
    const { createSecondBrainTransport } = await moduleAt('src/second-brain-transport.js');
    const transport = createSecondBrainTransport({ contractProfile: profile,
      launcherPath: body.transport.launcher, configPath: body.transport.config, contractPath: body.transport.contract });
    let withdrawAfterResponse = false;
    let substituteEmptyGeneration = false;
    const monitoredTransport = { call: async (...args) => {
        const outcome = await transport.call(...args);
        if (withdrawAfterResponse) writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
        if (substituteEmptyGeneration && outcome.kind === 'data' && Array.isArray(outcome.value.results)
          && outcome.value.results.length === 0) return { kind: 'data', value: { ...outcome.value,
            generation_id: 'sbgen:v1:' + '0'.repeat(64) } };
        return outcome;
      }, restart: () => transport.restart(), close: () => transport.close(), diagnostics: () => transport.diagnostics() };
    const client = createMemoryScopedClient({ issue, profile,
      status_issue: createProductionMemoryAccessClaim(db.authority, config, resolve, "memory_status"), now: () => new Date(body.issued_at),
      transport: monitoredTransport,
      budgets: { max_hits: 50, max_excerpt_bytes: 8192, max_total_bytes: 1000000, max_page_bytes: 100000 },
      max_age_ms: 86400000, expiry_ms: 172800000 });
    try {
      const before = profile === "scoped-record-read-v2" ? await client.status() : undefined;
      const page = await client.readPage(body.page_id);
      const search = await client.search('Cited', 2);
      const after = profile === "scoped-record-read-v2" ? await client.status() : undefined;
      if (before && JSON.stringify(before.generation) !== JSON.stringify(after.generation)) throw new Error('status changed');
      if (before && JSON.stringify(before.generation) !== JSON.stringify(search.generation)) throw new Error('read generation differs');
      let referenceCheck;
      let pendingReference;
      let reader;
      let scopedCliOptions;
      let callbacks = 0;
      if (profile === 'scoped-record-read-v2') {
        const { createProductionScopedMemory } = await moduleAt('src/memory-scoped-production.js');
        const projectionPath = join(db.root, 'memory-projection.key');
        writeFileSync(projectionPath, Buffer.alloc(32, 7), { mode: 0o600 });
        const productionOptions = { policy_path: policyPath, authenticated_session: sessionSource,
          read_fence_config: config, projection_key_path: projectionPath, clock: () => new Date(body.issued_at),
          transport_options: { launcherPath: body.transport.launcher, configPath: body.transport.config,
            contractPath: body.transport.contract } };
        scopedCliOptions = productionOptions;
        const { execute } = await moduleAt('src/cli-runtime.mjs');
        const cli = await execute(['memory', 'context', 'Cited', '--db', db.path, '--max_bytes', '32768'], {
          clock: () => new Date(body.issued_at), scopedMemoryReferenceOptions: productionOptions,
        });
        if (cli.command !== 'memory.context' || cli.context.records.length === 0
          || Buffer.byteLength(JSON.stringify({ version: 1, ...cli }) + '\n') > 32768)
          throw new Error('scoped CLI context or envelope budget invalid');
        const owned = createProductionScopedMemory(db.authority, productionOptions);
        try {
          const found = await owned.reader.read('Cited', { max_records: 8, max_record_bytes: 4096, max_bytes: 32768 });
          if (found.payload.records.length === 0) throw new Error('owned production transport returned no records');
        } finally { await owned.close(); await owned.close(); }
        const shared = createProductionScopedMemory(db.authority, { ...productionOptions, transport: monitoredTransport });
        reader = shared.reader;
        await shared.close(); // Injected transport remains caller-owned and usable.
        const budgets = { max_records: 8, max_record_bytes: 4096, max_bytes: 32768 };
        const reference = await reader.read('Cited', budgets);
        if (reference.payload.records.length === 0) throw new Error('reference did not contain actual records');
        const nativeSession = { client_id: "client:acceptance", session_id: "native:acceptance", epoch_id: "epoch:1" };
        await reader.submitInSession(reference, async serialized => {
          callbacks++;
          if (serialized !== reference.serialized || Buffer.byteLength(serialized) !== reference.bytes) throw new Error('payload mismatch');
        }, nativeSession);
        const { canonicalize } = await moduleAt('src/canonical.js');
        const { createMemoryMembership } = await moduleAt('src/memory-membership.js');
        const { memoryReadPrivacyState } = await moduleAt('src/memory-read-privacy.js');
        const membership = createMemoryMembership(Buffer.alloc(32, 7));
        const binding = canonicalize({ generation: before.generation,
          privacy: canonicalize(memoryReadPrivacyState(db.authority)), authorization: shared.client.authorizationIdentity() });
        const expectedBinding = membership('record', 'reference-delivery/binding/v1\0' + canonicalize(binding));
        const journal = db.authority.db.prepare('SELECT binding_key,state FROM personal_context_reference_sessions').get();
        if (journal.binding_key !== expectedBinding || journal.state !== 'active') throw new Error('scope missing from durable binding');
        const dump = JSON.stringify(db.authority.db.prepare('SELECT * FROM personal_context_reference_attempts').all());
        if (dump.includes(reference.serialized) || dump.includes(body.session_id)) throw new Error('raw delivery metadata leaked');
        const newReader = createProductionScopedMemory(db.authority, { ...productionOptions, transport: monitoredTransport }).reader;
        const reread = await newReader.read('Cited', budgets);
        let durableDuplicateDenied = false;
        try { await newReader.submitInSession(reread, async () => { callbacks++; }, nativeSession); }
        catch (error) { if (error.code !== 'MEMORY_REFERENCE_ALREADY_SUBMITTED') throw error; durableDuplicateDenied = true; }
        if (!durableDuplicateDenied || callbacks !== 1) throw new Error('durable duplicate accepted');
        const reopened = spawnSync(process.execPath,
          [fileURLToPath(new URL('./scoped-delivery-reopen.mjs', import.meta.url)), build], {
            input: JSON.stringify({ database: db.path, options: productionOptions,
              fixture_session: sessionSource(), now: body.issued_at, budgets, native_session: nativeSession }),
            encoding: 'utf8', timeout: 45000, maxBuffer: 1024 * 1024,
          });
        if (reopened.error) throw reopened.error;
        if (reopened.status !== 0) throw new Error(`independent delivery check failed: ${reopened.stderr}`);
        const processReplay = JSON.parse(reopened.stdout);
        if (!processReplay.independent_process || !processReplay.duplicate_denied || processReplay.callbacks !== 0)
          throw new Error('independent delivery evidence missing');
        let duplicateDenied = false;
        try { await reader.submit(reference, async () => { callbacks++; }); }
        catch (error) { if (error.code !== 'MEMORY_REFERENCE_SUBMISSION_INVALID') throw error; duplicateDenied = true; }
        if (!duplicateDenied || callbacks !== 1) throw new Error('duplicate reference submission');
        const empty = await reader.read('unmatchedscopeacceptance', budgets);
        if (empty.payload.state !== 'empty') throw new Error('empty query fixture mismatch');
        substituteEmptyGeneration = true;
        let generationDenied = false;
        try { await reader.read('unmatchedscopeacceptance', budgets); }
        catch (error) { if (error.code !== 'MEMORY_REFERENCE_GENERATION_CHANGED') throw error; generationDenied = true; }
        substituteEmptyGeneration = false;
        if (!generationDenied) throw new Error('empty generation substitution accepted');
        pendingReference = await reader.read('Cited', budgets);
        referenceCheck = { scoped_cli_records: cli.context.records.length, scoped_cli_budget_verified: true, independent_process_replay: processReplay, production_factory_owned_and_shared: true, durable_scope_binding_verified: true, durable_duplicate_denied: durableDuplicateDenied, records: reference.payload.records.length, bytes: reference.bytes, duplicate_denied: duplicateDenied, empty_generation_substitution_denied: generationDenied };
      }
      currentCookie = undefined;
      if (scopedCliOptions) {
        const { execute } = await moduleAt('src/cli-runtime.mjs');
        let cliDenied = false;
        try {
          await execute(['memory', 'context', 'Cited', '--db', db.path], {
            clock: () => new Date(body.issued_at), scopedMemoryReferenceOptions: scopedCliOptions,
          });
        } catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; cliDenied = true; }
        if (!cliDenied) throw new Error('scoped CLI accepted missing authentication');
        referenceCheck.scoped_cli_missing_cookie_denied = true;
      }
      if (reader) {
        let denied = false;
        try { await reader.submit(pendingReference, async () => { callbacks++; }); }
        catch (error) { if (error.code !== 'MEMORY_ACCESS_SCOPE_UNAVAILABLE') throw error; denied = true; }
        if (!denied || callbacks !== 1) throw new Error('unauthenticated reference delivery');
        referenceCheck.cookie_removed_before_submit_denied = true;
      }
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
      process.stdout.write(JSON.stringify({ reference_delivery: referenceCheck, profile, status_before_after_equal: before !== undefined, page_groups: page.pages.length, search_groups: search.pages.length,
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
