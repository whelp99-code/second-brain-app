// Real phone cookie -> scoped CLI -> MCP, using isolated operator policy/key fixtures.
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const at = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const { request } = await at('node_modules/undici/index.js');
const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await at('src/phone-gateway.js');
const { makePhoneHome, processUid, startFakeAuthority, cookieFromSetCookie,
  FIXTURE_HOST, FIXTURE_LOGIN, FIXTURE_ORIGIN } = await at('tests/fixtures/phone-gateway-harness.js');
const home = makePhoneHome();
let gateway;
let upstream;
try {
  const config = parsePhoneGatewayConfig({ home: home.home, envFile: home.envFile, uid: processUid() });
  const staticRoot = join(home.home, 'static'); mkdirSync(join(staticRoot, 'assets'), { recursive: true });
  writeFileSync(join(staticRoot, 'assets/app.js'), '1');
  writeFileSync(join(staticRoot, 'manifest.json'), JSON.stringify({ 'index.html': { file: 'assets/app.js' } }));
  const policyPath = join(home.home, 'policy.json');
  const providerPath = join(home.home, 'provider.toml');
  const memory = { ...input.options, policy_path: policyPath,
    transport_options: { ...input.options.transport_options, configPath: providerPath } };
  upstream = await startFakeAuthority();
  gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin, staticRoot, config,
    now: () => Date.parse(input.now), audit: () => {},
    memoryContext: { database_path: input.database, agent_id: input.agent_id, memory } });
  const base = `http://127.0.0.1:${gateway.address.port}`;
  const identity = { Host: FIXTURE_HOST, 'Tailscale-User-Login': FIXTURE_LOGIN };
  const login = await request(`${base}/api/v1/phone/session`, { headers: identity });
  assert.equal(login.statusCode, 200);
  const cookie = cookieFromSetCookie(login.headers['set-cookie']);
  const { csrf_token: csrf } = await login.body.json();
  // Test operator explicitly grants this authenticated session. Production does not auto-grant.
  const hmac = createHmac('sha256', config.sessionKey).update(cookie).digest();
  const sessionId = 'session:phone:' + createHash('sha256').update('orca-jarvis/phone-memory-session/v1\0').update(hmac).digest('hex');
  const policy = JSON.parse(readFileSync(input.options.policy_path, 'utf8'));
  const previous = policy.sessions[0].session_id;
  policy.sessions[0].session_id = sessionId;
  writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
  writeFileSync(providerPath, readFileSync(input.options.transport_options.configPath, 'utf8')
    .replace(`session = "${previous}"`, `session = "${sessionId}"`), { mode: 0o600 });
  const headers = { ...identity, Origin: FIXTURE_ORIGIN, Cookie: `__Host-jarvis-phone=${cookie}`,
    'X-JARVIS-CSRF': csrf, 'Content-Type': 'application/json; charset=utf-8' };
  const call = (extra = {}, selected = headers) => request(`${base}/api/v1/memory/context`, {
    method: 'POST', headers: selected,
    body: JSON.stringify({ schema_version: 1, query: 'Cited', limit: 8, max_bytes: 32768, ...extra }),
  });
  const found = await call(); assert.equal(found.statusCode, 200);
  const text = await found.body.text(); const result = JSON.parse(text);
  assert.equal(result.context.records.length, 2); assert.ok(Buffer.byteLength(text) <= 32768);
  const tampered = await call({ agent_id: 'agent:attacker' }); assert.equal(tampered.statusCode, 400); await tampered.body.text();
  const missing = await call({}, { ...headers, Cookie: '' }); assert.equal(missing.statusCode, 401); await missing.body.text();
  const noCsrf = await call({}, { ...headers, 'X-JARVIS-CSRF': '' }); assert.equal(noCsrf.statusCode, 403); await noCsrf.body.text();
  const secondLogin = await request(`${base}/api/v1/phone/session`, { headers: identity });
  assert.equal(secondLogin.statusCode, 200);
  const secondCookie = cookieFromSetCookie(secondLogin.headers['set-cookie']);
  const secondCsrf = (await secondLogin.body.json()).csrf_token;
  const otherSession = await call({}, { ...headers, Cookie: `__Host-jarvis-phone=${secondCookie}`, 'X-JARVIS-CSRF': secondCsrf });
  assert.equal(otherSession.statusCode, 502); await otherSession.body.text();
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
  const revoked = await call(); assert.equal(revoked.statusCode, 502);
  const revokedBody = await revoked.body.text(); assert.ok(!revokedBody.includes('context_digest'));
  assert.ok(!upstream.captures.some(row => row.url === '/api/v1/memory/context'));
  process.stdout.write(JSON.stringify({ records: 2, bytes: Buffer.byteLength(text), cookie_required: true,
    client_identity_denied: true, csrf_required: true, ungranted_login_session_denied: true,
    policy_withdrawal_denied: true, direct_scoped_mcp: true,
    scope: 'real HTTP cookie and MCP; fixture Tailnet headers, keys, explicit session grant, source and clock' }));
} finally {
  gateway?.close();
  try { await upstream?.close(); } finally { rmSync(home.home, { recursive: true, force: true }); }
}
