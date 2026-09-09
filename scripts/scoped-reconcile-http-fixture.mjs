import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Actual HTTP login/CSRF and gateway-owned session, with isolated authority,
// fixed fixture clock and trusted-header forwarder assumptions.
export async function reconcileThroughHttp(build, options, outboxId, at) {
  const load = p => import(pathToFileURL(join(build, p)).href);
  const { request } = await import(pathToFileURL(join(build, 'node_modules/undici/index.js')).href);
  const { parsePhoneGatewayCli } = await load('src/phone-gateway-main.js');
  const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await load('src/phone-gateway.js');
  const { FIXTURE_HOST, FIXTURE_LOGIN, FIXTURE_ORIGIN, cookieFromSetCookie, makePhoneHome,
    processUid, startFakeAuthority } = await load('tests/fixtures/phone-gateway-harness.js');
  const home = makePhoneHome(), upstream = await startFakeAuthority();
  const staticRoot = join(home.home, 'static');
  mkdirSync(join(staticRoot, 'assets'), { recursive: true });
  writeFileSync(join(staticRoot, 'index.html'), '<div id="root"></div>');
  writeFileSync(join(staticRoot, 'manifest.json'), JSON.stringify({ 'index.html': { file: 'assets/app.js' } }));
  writeFileSync(join(staticRoot, 'assets/app.js'), '1');
  const config = parsePhoneGatewayConfig({ home: home.home, envFile: home.envFile, uid: processUid() });
  const memory = options.memory;
  const fields = { 'reconcile-db': options.database_path, 'reconcile-agent': options.agent_id,
    'reconcile-policy': memory.policy_path, 'reconcile-provider': memory.read_fence_config.provider_instance_id,
    'reconcile-signing-key': memory.read_fence_config.signing_key_id, 'reconcile-private-key': memory.read_fence_config.private_key_path,
    'reconcile-spool': memory.spool_root,
    'reconcile-dispatch-spool': memory.roots.candidate_dispatch_spool_root ?? join(home.home, 'unused-dispatch'),
    'reconcile-review-spool': memory.roots.candidate_review_spool_root ?? join(home.home, 'unused-review'),
    'reconcile-launcher': memory.journal_transport_options.launcherPath,
    'reconcile-provider-config': memory.journal_transport_options.configPath,
    'reconcile-journal-contract': memory.journal_transport_options.contractPath,
    'reconcile-read-contract': memory.completion_transport_options.contractPath };
  const parsed = parsePhoneGatewayCli(['--host', '127.0.0.1', '--port', '4176', '--upstream', 'http://127.0.0.1:4173',
    '--static-root', staticRoot, '--env-file', home.envFile, ...Object.entries(fields).flatMap(([key, value]) => [`--${key}`, value])]);
  assert.equal(parsed.memoryReconcile.database_path, options.database_path);
  let clock = at.getTime();
  const logs = [];
  const gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin,
    staticRoot, config, now: () => clock, audit: line => logs.push(line), memoryReconcile: parsed.memoryReconcile });
  try {
    const origin = `http://127.0.0.1:${gateway.address.port}`;
    const login = await request(`${origin}/api/v1/phone/session`, { headers: { Host: FIXTURE_HOST, 'Tailscale-User-Login': FIXTURE_LOGIN } });
    assert.equal(login.statusCode, 200);
    const cookie = cookieFromSetCookie(login.headers['set-cookie']);
    const csrf = (await login.body.json()).csrf_token;
    const headers = { Host: FIXTURE_HOST, 'Tailscale-User-Login': FIXTURE_LOGIN, Origin: FIXTURE_ORIGIN,
      Cookie: `__Host-jarvis-phone=${cookie}`, 'X-JARVIS-CSRF': csrf, 'Content-Type': 'application/json; charset=utf-8' };
    const body = JSON.stringify({ schema_version: 1, outbox_id: outboxId });
    const call = (changed = {}, payload = body) => request(`${origin}/api/v1/memory/reconcile`, { method: 'POST', headers: { ...headers, ...changed }, body: payload });
    for (const [changed, status] of [[{ Cookie: '' }, 401], [{ 'X-JARVIS-CSRF': 'wrong' }, 403], [{ Origin: 'https://other.invalid' }, 403]]) {
      const denied = await call(changed); assert.equal(denied.statusCode, status); await denied.body.text();
    }
    const forged = await call({}, JSON.stringify({ schema_version: 1, outbox_id: outboxId, session_id: 'session:forged' }));
    assert.equal(forged.statusCode, 400); await forged.body.text();
    const policy = readFileSync(options.memory.policy_path, 'utf8');
    writeFileSync(options.memory.policy_path, JSON.stringify({ ...JSON.parse(policy), agents: [] }));
    const forbidden = await call(); assert.equal(forbidden.statusCode, 403); await forbidden.body.text();
    writeFileSync(options.memory.policy_path, policy);
    const normal = await call(), normalBody = await normal.body.text();
    assert.equal(normal.statusCode, 200, normalBody);
    const response = JSON.parse(normalBody);
    const replay = await call(); assert.equal(replay.statusCode, 200); await replay.body.text();
    clock = at.getTime() + 15 * 60000 + 5;
    const expired = await call(); assert.equal(expired.statusCode, 401); await expired.body.text();
    assert.equal(upstream.captures.some(row => row.url === '/api/v1/memory/reconcile'), false);
    assert.equal(logs.join('\n').includes(cookie), false);
    return response;
  } finally { gateway.close(); await upstream.close(); rmSync(home.home, { recursive: true, force: true }); }
}
