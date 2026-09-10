// Same admitted and executed provider data, fresh reader login and real MCP client.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { acceptPhoneMemoryClient } from './phone-memory-client-acceptance.mjs';
export async function acceptWrittenContext({ build, sb, f, home, upstream, config, assets, result, request: written, outboxId, writerCookie, query: contextQuery }) {
  const load = name => import(pathToFileURL(join(build, name)).href);
  const { createPhoneGatewayServer } = await load('src/phone-gateway.js');
  const { parsePhoneGatewayCli } = await load('src/phone-gateway-main.js');
  const { memoryReadFenceFixture } = await load('tests/fixtures/memory-read-fence.js');
  const { cookieFromSetCookie, FIXTURE_LOGIN } = await load('tests/fixtures/phone-gateway-harness.js');
  const { request } = await load('node_modules/undici/index.js');
  const root = join(f.database.root, 'context-reader'); mkdirSync(root, { mode: 0o700 });
  const at = new Date('2026-08-31T03:30:00.000Z');
  const { config: readKey } = memoryReadFenceFixture(f.database);
  const policy = join(root, 'policy.json'), projection = join(root, 'projection.key');
  writeFileSync(projection, Buffer.alloc(32, 7), { mode: 0o600 });
  const scope = written.preparation.binding.identity;
  const policyValue = { schema_version: 3, provider_instance_id: 'provider:fixture', principal_id: 'principal:owner',
    policy_revision: scope.policy_revision, valid_from: at.toISOString(), valid_until: '2026-08-31T03:40:00.000Z',
    agents: [{ agent_id: 'agent:reader', projects: scope.projects, methods: ['sb_generation_status', 'sb_read_page', 'sb_request_status', 'sb_search'] }] };
  writeFileSync(policy, JSON.stringify(policyValue), { mode: 0o600 });
  const fields = { 'memory-db': f.database.path, 'memory-agent': 'agent:reader', 'memory-policy': policy,
    'memory-provider': 'provider:fixture', 'memory-signing-key': readKey.signing_key_id,
    'memory-private-key': readKey.private_key_path, 'memory-projection-key': projection,
    'memory-launcher': result.readback.launcher, 'memory-provider-config': result.readback.config,
    'memory-contract': join(sb, 'contracts/second-brain-scoped-read-v2.json'),
    'reconcile-db': f.database.path, 'reconcile-agent': 'agent:reader', 'reconcile-policy': policy,
    'reconcile-provider': 'provider:fixture', 'reconcile-signing-key': readKey.signing_key_id,
    'reconcile-private-key': readKey.private_key_path, 'reconcile-spool': f.options.spoolRoot,
    'reconcile-dispatch-spool': f.dispatch.roots.dispatch, 'reconcile-review-spool': f.dispatch.roots.review,
    'reconcile-launcher': result.readback.launcher, 'reconcile-provider-config': result.readback.config,
    'reconcile-journal-contract': join(sb, 'contracts/second-brain-scoped-status-v1.json'),
    'reconcile-read-contract': join(sb, 'contracts/second-brain-scoped-read-v5.json') };
  const parsed = parsePhoneGatewayCli(['--host', '127.0.0.1', '--port', '4176', '--upstream', 'http://127.0.0.1:4173',
    '--static-root', assets, '--env-file', home.envFile,
    ...Object.entries(fields).flatMap(([key, value]) => [`--${key}`, value])]);
  const gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin,
    staticRoot: assets, config, now: () => at.getTime(), audit: () => {}, memoryContext: parsed.memoryContext, memoryReconcile: parsed.memoryReconcile });
  try {
    const base = `http://127.0.0.1:${gateway.address.port}`;
    const identity = { Host: config.publicHost, 'Tailscale-User-Login': FIXTURE_LOGIN };
    const login = await request(`${base}/api/v1/phone/session`, { headers: identity });
    assert.equal(login.statusCode, 200);
    const cookie = cookieFromSetCookie(login.headers['set-cookie']);
    const csrf = (await login.body.json()).csrf_token;
    assert.notEqual(cookie, writerCookie);
    // Fixture bodies contain '결정'; a real work item supplies a term from its own statement.
    const query = contextQuery ?? '결정';
    const headers = { ...identity, Origin: config.publicOrigin, Cookie: `__Host-jarvis-phone=${cookie}`,
      'X-JARVIS-CSRF': csrf, 'Content-Type': 'application/json; charset=utf-8' };
    const reconcile = () => request(`${base}/api/v1/memory/reconcile`, { method: 'POST', headers,
      body: JSON.stringify({ schema_version: 1, outbox_id: outboxId }) });
    const settled = await reconcile(); const settlement = await settled.body.json();
    assert.equal(settled.statusCode, 200, JSON.stringify(settlement));
    assert.equal(settlement.result.kind, 'memory_scoped_settled');
    const replay = await reconcile(); const replayed = await replay.body.json();
    assert.equal(replay.statusCode, 200); assert.equal(replayed.result.replayed, true);
    const db = f.database.authority.db;
    assert.equal(db.prepare('SELECT state FROM memory_outbox WHERE outbox_id=?').get(outboxId).state, 'settled');
    assert.equal(db.prepare('SELECT state FROM control_command_requests WHERE request_id=?').get(f.claimed.request_id).state, 'completed');
    assert.equal(db.prepare('SELECT count(*) AS n FROM memory_scoped_settlements').get().n, 1);
    assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
    const read = await request(`${base}/api/v1/memory/context`, { method: 'POST', headers,
      body: JSON.stringify({ schema_version: 1, query, limit: 8, max_bytes: 32768 }) });
    const body = await read.body.json(); assert.equal(read.statusCode, 200, JSON.stringify(body));
    const records = body.context.records;
    assert(records.length > 0, 'completed scoped write was not discoverable through context search');
    assert.equal(result.readback.proof.request_id, written.request_id);
    assert.equal(result.readback.proof.request_digest, written.request_digest);
    assert.equal(result.readback.proof.content_digest, `sha256:${createHash("sha256").update(written.preparation.payload.content).digest("hex")}`);
    for (const record of records) {
      assert(written.preparation.payload.content.includes(record.text));
      assert.equal(record.record.generation.generation_id, result.readback.proof.generation_id);
    }
    const clients = await acceptPhoneMemoryClient({ build, root, port: gateway.address.port, identity,
      origin: config.publicOrigin, cookie, csrf, expected: records, query });
    writeFileSync(policy, JSON.stringify({ ...policyValue, agents: [] }));
    const denied = await request(`${base}/api/v1/memory/context`, { method: 'POST', headers,
      body: JSON.stringify({ schema_version: 1, query, limit: 8, max_bytes: 32768 }) });
    await denied.body.text(); assert.equal(denied.statusCode, 403);
    return { request_id: written.request_id, request_digest: written.request_digest,
      writer_agent: 'agent:fixture', reader_agent: 'agent:reader', fresh_login: true,
      provider_proved: true, jarvis_settled: true, control_completed: true, settlement_replay: true, settlements: 1, attempts: 1, same_generation: true, record_ids: records.map(row => row.record.record_id),
      source_refs: records.map(row => row.source_ref), context_records: records.length, clients, reader_revocation: 403,
      limits: 'fixture verified task and reviewed content; native submission is reported separately; not operational deployment' };
  } finally { gateway.close(); }
}
