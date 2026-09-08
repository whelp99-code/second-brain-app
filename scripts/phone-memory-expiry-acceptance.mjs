// Real HTTP gateway from an isolated JARVIS build; fixture upstream/identity/clock.
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const moduleAt = name => import(pathToFileURL(join(process.argv[2], name)).href);
const { request } = await moduleAt('node_modules/undici/index.js');
const fetchFixture = async (url, options) => {
  const result = await request(url, options);
  return { status: result.statusCode, headers: { get: name => {
    const value = result.headers[name];
    return Array.isArray(value) ? value[0] : value;
  } }, json: () => result.body.json(), text: () => result.body.text() };
};
const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await moduleAt('src/phone-gateway.js');
const { makePhoneHome, processUid, startFakeAuthority, json, cookieFromSetCookie,
  FIXTURE_HOST, FIXTURE_LOGIN, FIXTURE_ORIGIN } = await moduleAt('tests/fixtures/phone-gateway-harness.js');
const files = makePhoneHome();
let gateway;
let authority;
let now = Date.parse('2026-09-09T00:00:00.000Z');
let expire = false;
let reads = 0;
const audits = [];
try {
  const assets = join(files.home, 'static');
  mkdirSync(join(assets, 'assets'), { recursive: true });
  writeFileSync(join(assets, 'index.html'), '<!doctype html><div id="root"></div>');
  writeFileSync(join(assets, 'assets/app.js'), '1');
  writeFileSync(join(assets, 'manifest.json'), JSON.stringify({ 'index.html': { file: 'assets/app.js' } }));
  authority = await startFakeAuthority((request, response) => {
    if (request.url !== '/api/v1/memory/status') return false;
    reads++;
    if (expire) now += 16 * 60_000;
    json(response, 200, { schema_version: 1, private_memory: 'fixture-memory-marker' });
    return true;
  });
  gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: authority.origin,
    staticRoot: assets, config: parsePhoneGatewayConfig({ home: files.home, envFile: files.envFile, uid: processUid() }),
    now: () => now, audit: line => audits.push(JSON.parse(line)) });
  const base = `http://127.0.0.1:${gateway.address.port}`;
  const identity = { Host: FIXTURE_HOST, 'Tailscale-User-Login': FIXTURE_LOGIN };
  const session = await fetchFixture(`${base}/api/v1/phone/session`, { headers: identity });
  assert.equal(session.status, 200);
  const cookie = cookieFromSetCookie(session.headers.get('set-cookie'));
  const { csrf_token: csrf } = await session.json();
  const headers = { ...identity, Origin: FIXTURE_ORIGIN,
    Cookie: `__Host-jarvis-phone=${cookie}`, 'X-JARVIS-CSRF': csrf };
  const normal = await fetchFixture(`${base}/api/v1/memory/status`, { headers });
  assert.equal(normal.status, 200);
  assert.equal((await normal.json()).private_memory, 'fixture-memory-marker');
  expire = true;
  const expired = await fetchFixture(`${base}/api/v1/memory/status`, { headers });
  assert.equal(expired.status, 401);
  const denied = await expired.text();
  assert.match(denied, /PHONE_SESSION_REQUIRED/);
  assert.ok(!denied.includes('fixture-memory-marker'));
  assert.match(expired.headers.get('set-cookie'), /Max-Age=0/);
  const retry = await fetchFixture(`${base}/api/v1/memory/status`, { headers });
  assert.equal(retry.status, 401);
  await retry.text();
  assert.equal(reads, 2);
  assert.ok(audits.some(row => row.status === 401 && row.outcome === 'rejected'));
  process.stdout.write(JSON.stringify({ normal_status: 200, expired_status: 401, retry_status: 401,
    upstream_reads: reads, expired_payload_withheld: true, expired_cookie_cleared: true,
    scope: 'compiled HTTP gateway; fixture Tailnet headers/upstream/clock; no live Tailnet or scoped MCP composition' }) + '\n');
} finally {
  gateway?.close();
  try { await authority?.close(); } finally { rmSync(files.home, { recursive: true, force: true }); }
}
