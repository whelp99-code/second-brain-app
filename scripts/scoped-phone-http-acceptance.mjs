// Real phone cookie -> scoped CLI -> MCP, using isolated operator policy/key fixtures.
import assert from 'node:assert/strict';
import { acceptPhoneMemoryClient } from './phone-memory-client-acceptance.mjs';
import { createHash, createHmac } from 'node:crypto';
import { execFile } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const at = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const { request } = await at('node_modules/undici/index.js');
const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await at('src/phone-gateway.js');
const { parsePhoneGatewayCli } = await at('src/phone-gateway-main.js');
const { makePhoneHome, processUid, startFakeAuthority, cookieFromSetCookie,
  FIXTURE_HOST, FIXTURE_LOGIN, FIXTURE_ORIGIN } = await at('tests/fixtures/phone-gateway-harness.js');
const home = makePhoneHome();
let gateway;
let peer;
let upstream;
let now = Date.parse(input.now);
let expireOnExit = false;
let expiryExitObserved = false;
try {
  const config = parsePhoneGatewayConfig({ home: home.home, envFile: home.envFile, uid: processUid() });
  const staticRoot = join(home.home, 'static'); mkdirSync(join(staticRoot, 'assets'), { recursive: true });
  writeFileSync(join(staticRoot, 'assets/app.js'), '1');
  writeFileSync(join(staticRoot, 'manifest.json'), JSON.stringify({ 'index.html': { file: 'assets/app.js' } }));
  const policyPath = join(home.home, 'policy.json');
  const providerPath = join(home.home, 'provider.toml');
  const memory = { ...input.options, policy_path: policyPath,
    transport_options: { ...input.options.transport_options, configPath: providerPath,
      execFile: (file, args, options) => {
        const child = execFile(file, [...args], options);
        child.once('exit', () => {
          if (expireOnExit) { expiryExitObserved = true; now += 16 * 60_000; }
        });
        return child;
      } } };
  upstream = await startFakeAuthority();
  const parsed = parsePhoneGatewayCli(['--host', '127.0.0.1', '--port', '4176',
    '--upstream', 'http://127.0.0.1:4173', '--static-root', staticRoot, '--env-file', home.envFile,
    '--memory-db', input.database, '--memory-agent', input.agent_id, '--memory-policy', policyPath,
    '--memory-provider', memory.read_fence_config.provider_instance_id,
    '--memory-signing-key', memory.read_fence_config.signing_key_id,
    '--memory-private-key', memory.read_fence_config.private_key_path,
    '--memory-projection-key', memory.projection_key_path,
    '--memory-launcher', memory.transport_options.launcherPath, '--memory-provider-config', providerPath,
    '--memory-contract', memory.transport_options.contractPath]);
  assert.ok(parsed.memoryContext);
  gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin, staticRoot, config,
    now: () => now, audit: () => {},
    memoryContext: { ...parsed.memoryContext, memory: { ...parsed.memoryContext.memory,
      transport_options: { ...parsed.memoryContext.memory.transport_options,
        execFile: memory.transport_options.execFile } } } });
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
  const capabilities = await request(`${base}/api/v1/memory/context/capabilities`, { headers });
  assert.equal(capabilities.statusCode, 200);
  const supported = await capabilities.body.json();
  assert.equal(supported.configured, true); assert.equal(supported.writes_supported, false);
  assert.deepEqual(supported.supported_operations, ['context']);
  assert.equal(supported.readiness, 'not_checked');
  const forbiddenWrite = await request(`${base}/api/v1/memory/remember`, { method: 'POST', headers,
    body: JSON.stringify({ schema_version: 1, content: 'must-not-write' }) });
  assert.equal(forbiddenWrite.statusCode, 404); await forbiddenWrite.body.text();
  assert.ok(!upstream.captures.some(row => row.url === '/api/v1/memory/remember'));
  const call = (extra = {}, selected = headers) => request(`${base}/api/v1/memory/context`, {
    method: 'POST', headers: selected,
    body: JSON.stringify({ schema_version: 1, query: 'Cited', limit: 8, max_bytes: 32768, ...extra }),
  });
  const found = await call();
  const text = await found.body.text(); const result = JSON.parse(text);
  assert.equal(found.statusCode, 200, `context request failed: ${result.error?.code ?? "unknown"}`);
  assert.equal(result.context.records.length, 2); assert.ok(Buffer.byteLength(text) <= 32768);
  const clientAcceptance = await acceptPhoneMemoryClient({ build: process.argv[2], root: home.home,
    port: gateway.address.port, identity, origin: FIXTURE_ORIGIN, cookie, csrf, expected: result.context.records });
  const tampered = await call({ agent_id: 'agent:attacker' }); assert.equal(tampered.statusCode, 400); await tampered.body.text();
  const missing = await call({}, { ...headers, Cookie: '' }); assert.equal(missing.statusCode, 401); await missing.body.text();
  const noCsrf = await call({}, { ...headers, 'X-JARVIS-CSRF': '' }); assert.equal(noCsrf.statusCode, 403); await noCsrf.body.text();
  const secondLogin = await request(`${base}/api/v1/phone/session`, { headers: identity });
  assert.equal(secondLogin.statusCode, 200);
  const secondCookie = cookieFromSetCookie(secondLogin.headers['set-cookie']);
  const secondCsrf = (await secondLogin.body.json()).csrf_token;
  const otherSession = await call({}, { ...headers, Cookie: `__Host-jarvis-phone=${secondCookie}`, 'X-JARVIS-CSRF': secondCsrf });
  assert.equal(otherSession.statusCode, 403);
  assert.equal((await otherSession.body.json()).error.code, 'PHONE_MEMORY_SCOPE_FORBIDDEN');
  const fixedProvider = readFileSync(providerPath, 'utf8');
  const { sessions: sessionGrants, ...policyBase } = policy;
  const agentPolicy = { ...policyBase, schema_version: 2,
    agents: sessionGrants.map(row => ({ agent_id: row.agent_id, projects: row.projects, methods: row.methods })) };
  const agentPolicyBytes = JSON.stringify(agentPolicy);
  writeFileSync(policyPath, agentPolicyBytes);
  const issuerProvider = fixedProvider.replace(`session = "${sessionId}"`, 'session_mode = "issuer_authenticated"');
  assert.notEqual(issuerProvider, fixedProvider);
  writeFileSync(providerPath, issuerProvider);
  const secondAllowed = await call({}, { ...headers, Cookie: `__Host-jarvis-phone=${secondCookie}`, 'X-JARVIS-CSRF': secondCsrf });
  assert.equal(secondAllowed.statusCode, 200); assert.equal((await secondAllowed.body.json()).context.records.length, 2);
  const thirdLogin = await request(`${base}/api/v1/phone/session`, { headers: identity });
  assert.equal(thirdLogin.statusCode, 200);
  const thirdCookie = cookieFromSetCookie(thirdLogin.headers['set-cookie']);
  const thirdCsrf = (await thirdLogin.body.json()).csrf_token;
  const thirdHeaders = { ...headers, Cookie: `__Host-jarvis-phone=${thirdCookie}`, 'X-JARVIS-CSRF': thirdCsrf };
  const thirdAllowed = await call({}, thirdHeaders);
  assert.equal(thirdAllowed.statusCode, 200); assert.equal((await thirdAllowed.body.json()).context.records.length, 2);
  assert.equal(readFileSync(policyPath, 'utf8'), agentPolicyBytes);
  assert.equal(readFileSync(providerPath, 'utf8'), issuerProvider);
  // A separate configured agent and cookie store use the same canonical provider/DB.
  const peerAgent = 'agent:shared-memory-peer';
  const peerProviderPath = join(home.home, 'peer-provider.toml');
  const peerProvider = issuerProvider.replace(`agent = "${input.agent_id}"`, `agent = "${peerAgent}"`);
  assert.notEqual(peerProvider, issuerProvider);
  writeFileSync(peerProviderPath, peerProvider, { mode: 0o600 });
  const peerGrant = { ...agentPolicy.agents[0], agent_id: peerAgent };
  writeFileSync(policyPath, JSON.stringify({ ...agentPolicy, agents: [...agentPolicy.agents, peerGrant] }));
  peer = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin, staticRoot, config,
    now: () => now, audit: () => {}, memoryContext: { ...parsed.memoryContext, agent_id: peerAgent,
      memory: { ...parsed.memoryContext.memory, transport_options: { ...parsed.memoryContext.memory.transport_options,
        configPath: peerProviderPath } } } });
  const peerBase = `http://127.0.0.1:${peer.address.port}`;
  const peerLogin = await request(`${peerBase}/api/v1/phone/session`, { headers: identity });
  assert.equal(peerLogin.statusCode, 200);
  const peerCookie = cookieFromSetCookie(peerLogin.headers['set-cookie']);
  const peerCsrf = (await peerLogin.body.json()).csrf_token;
  const peerHeaders = { ...headers, Cookie: `__Host-jarvis-phone=${peerCookie}`, 'X-JARVIS-CSRF': peerCsrf };
  const peerCall = () => request(`${peerBase}/api/v1/memory/context`, { method: 'POST', headers: peerHeaders,
    body: JSON.stringify({ schema_version: 1, query: 'Cited', limit: 8, max_bytes: 32768 }) });
  const shared = await peerCall(); assert.equal(shared.statusCode, 200);
  const sharedContext = (await shared.body.json()).context;
  assert.deepEqual(sharedContext.records, result.context.records);
  writeFileSync(policyPath, JSON.stringify({ ...agentPolicy, agents: [...agentPolicy.agents,
    { ...peerGrant, projects: ['project:isolated-peer'] }] }));
  const isolated = await peerCall(); assert.equal(isolated.statusCode, 200);
  const isolatedContext = (await isolated.body.json()).context;
  assert.equal(isolatedContext.state, 'empty'); assert.deepEqual(isolatedContext.records, []);
  const firstStillAllowed = await call(); assert.equal(firstStillAllowed.statusCode, 200);
  assert.equal((await firstStillAllowed.body.json()).context.records.length, 2);
  peer.close(); peer = undefined;
  writeFileSync(policyPath, JSON.stringify({ ...agentPolicy, agents: [] }));
  const agentRevoked = await call({}, thirdHeaders); assert.equal(agentRevoked.statusCode, 403); await agentRevoked.body.text();
  writeFileSync(policyPath, JSON.stringify(policy)); writeFileSync(providerPath, fixedProvider);
  const invalidQuery = await call({ query: 'bad\u0000query' });
  assert.equal(invalidQuery.statusCode, 400);
  assert.equal((await invalidQuery.body.json()).error.code, 'PHONE_REQUEST_INVALID');
  writeFileSync(policyPath, JSON.stringify({ ...policy, sessions: [] }));
  const revoked = await call(); assert.equal(revoked.statusCode, 403);
  const revokedBody = await revoked.body.text(); assert.ok(!revokedBody.includes('context_digest'));
  assert.equal(JSON.parse(revokedBody).error.code, 'PHONE_MEMORY_SCOPE_FORBIDDEN');
  writeFileSync(policyPath, JSON.stringify(policy));
  expireOnExit = true;
  const expired = await call(); assert.equal(expired.statusCode, 401);
  assert.equal((await expired.body.json()).error.code, 'PHONE_SESSION_REQUIRED');
  assert.ok(expiryExitObserved);
  assert.ok(String(expired.headers['set-cookie']).includes('Max-Age=0'));
  assert.ok(!upstream.captures.some(row => row.url === '/api/v1/memory/context'));
  process.stdout.write(JSON.stringify({ client_acceptance: clientAcceptance, agent_policy_new_sessions_without_policy_edits: 2,
    capabilities_verified: true, unsupported_write_http_status: forbiddenWrite.statusCode,
    independent_agent_shared_records_equal: true, restricted_peer_records: isolatedContext.records.length,
    original_agent_records_after_peer_restriction: 2,
    agent_policy_withdrawal_denied: true, cli_activation_parsed: true, records: 2, bytes: Buffer.byteLength(text), cookie_required: true,
    client_identity_denied: true, csrf_required: true, ungranted_login_session_denied: true,
    policy_withdrawal_denied: true, policy_withdrawal_http_status: revoked.statusCode,
    invalid_query_http_status: invalidQuery.statusCode, direct_scoped_mcp: true,
    cleanup_session_expiry_http_status: expired.statusCode, expiry_child_exit_observed: expiryExitObserved,
    scope: 'real HTTP cookie and MCP; fixture Tailnet headers, keys, explicit session grant, source and clock' }));
} finally {
  peer?.close();
  gateway?.close();
  try { await upstream?.close(); } finally { rmSync(home.home, { recursive: true, force: true }); }
}
