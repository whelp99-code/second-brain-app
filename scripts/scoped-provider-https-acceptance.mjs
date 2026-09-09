// Actual TLS + gateway sessions + Python provider; forwarder identity is a fixture.
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, rmSync, chmodSync, lstatSync, readdirSync } from 'node:fs';
import { createServer as httpsServer, request as httpsRequest } from 'node:https';
import { request as httpRequest } from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const build = resolve(process.argv[2]);
const load = path => import(pathToFileURL(join(build, path)).href);
const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
const { makePhoneHome, processUid, startFakeAuthority, FIXTURE_LOGIN, cookieFromSetCookie } = await load('tests/fixtures/phone-gateway-harness.js');
const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await load('src/phone-gateway.js');
const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch } = await load('src/memory-scoped-outbox-worker.js');
const { recordMemoryScopedOutboxAcceptance } = await load('src/memory-scoped-outbox-result.js');
const { canonicalize } = await load('src/canonical.js');
const results = [];
for (const mode of ['valid', 'revoke_during_accept', 'revoke_before_execute', 'expire_before_execute']) {
  const f = await scopedOutboxFixture(), home = makePhoneHome(), upstream = await startFakeAuthority();
  let gateway, tls;
  try {
    const generated = spawnSync(join(sb, '.venv/bin/python'), ['-c',
      'from pathlib import Path; import sys; from tests.scoped_https_harness import certificate; certificate(Path(sys.argv[1]))', f.database.root],
      { cwd: sb, encoding: 'utf8' });
    assert.equal(generated.status, 0, generated.stderr);
    const ca = readFileSync(join(f.database.root, 'tls-cert.pem'));
    const policyPath = join(f.database.root, 'https-policy.json');
    let calls = 0, at = f.now.getTime();
    tls = httpsServer({ cert: ca, key: readFileSync(join(f.database.root, 'tls-key.pem')) }, (req, res) => {
      if (req.url === '/api/v1/memory/provider/verify') {
        calls++;
        if ((mode === 'revoke_during_accept' && calls === 2) || (mode === 'revoke_before_execute' && calls === 3)) {
          const policy = JSON.parse(readFileSync(policyPath, 'utf8')); policy.agents = [];
          writeFileSync(policyPath, JSON.stringify(policy));
        }
        if (mode === 'expire_before_execute' && calls === 3) at += 16 * 60000;
      }
      const forwarded = httpRequest({ host: '127.0.0.1', port: gateway.address.port, method: req.method, path: req.url,
        headers: { ...req.headers, 'tailscale-user-login': FIXTURE_LOGIN } }, reply => {
        res.writeHead(reply.statusCode, reply.headers); reply.pipe(res);
      });
      forwarded.on('error', () => { res.writeHead(502); res.end(); }); req.pipe(forwarded);
    });
    await new Promise(resolve => tls.listen(0, '127.0.0.1', resolve));
    const origin = `https://127.0.0.1:${tls.address().port}`;
    // Test forwarder uses a temporary port/IP; production retains its configured Tailnet host.
    const parsed = parsePhoneGatewayConfig({ home: home.home, envFile: home.envFile, uid: processUid() });
    const config = { ...parsed, publicOrigin: origin, publicHost: new URL(origin).host };
    const assets = join(f.database.root, 'static'); mkdirSync(join(assets, 'assets'), { recursive: true });
    writeFileSync(join(assets, 'index.html'), '<div id="root"></div>');
    writeFileSync(join(assets, 'manifest.json'), JSON.stringify({ 'index.html': { file: 'assets/app.js' } }));
    writeFileSync(join(assets, 'assets/app.js'), '1');
    gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin, staticRoot: assets,
      config, now: () => at, audit: () => {}, memoryProviderVerifier: { authority: f.database.authority,
        agent_id: 'agent:fixture', provider_instance_id: 'provider:fixture', policy_path: policyPath,
        spool_root: f.options.spoolRoot, roots: f.dispatch.roots } });
    const login = await new Promise((resolve, reject) => {
      const req = httpsRequest(`${origin}/api/v1/phone/session`, { ca }, res => {
        let body = ''; res.on('data', chunk => { body += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: JSON.parse(body) }));
      }); req.on('error', reject); req.end();
    });
    assert.equal(login.status, 200);
    const cookie = cookieFromSetCookie(login.headers['set-cookie']);
    const hmac = createHmac('sha256', config.sessionKey).update(cookie).digest();
    const sessionId = `session:phone:${createHash('sha256').update('orca-jarvis/phone-memory-session/v1\0').update(hmac).digest('hex')}`;
    const options = { ...f.options, roots: f.dispatch.roots,
      resolveWriteScope: now => ({ ...f.options.resolveWriteScope(now), session_id: sessionId }) };
    const registered = registerMemoryScopedOutbox(options, f.claimed);
    const lease = claimMemoryScopedOutbox(options, registered.outbox_id, 'worker:https', 1000);
    const dispatched = markMemoryScopedOutboxDispatch(options, lease, 30000);
    writeFileSync(policyPath, JSON.stringify({ schema_version: 3, provider_instance_id: 'provider:fixture',
      principal_id: 'principal:owner', policy_revision: 'policy:1', valid_from: f.now.toISOString(),
      valid_until: dispatched.request.expires_at, agents: [{ agent_id: 'agent:fixture', projects: ['project:a'], methods: ['sb_write_request'] }] }), { mode: 0o600 });
    const credentials = join(f.database.root, 'https-credentials.json');
    writeFileSync(credentials, canonicalize({ origin, cookie_id: cookie, csrf_token: login.body.csrf_token,
      ca_file: join(f.database.root, 'tls-cert.pem') }), { mode: 0o600 });
    const state = join(f.database.root, 'https-state.json');
    writeFileSync(state, JSON.stringify({ credentials, mode, request: dispatched.request,
      execution_surface: process.argv.includes('--cli') ? 'cli' : 'internal',
      at: f.now.toISOString(), provider_root: join(f.database.root, 'provider') }), { mode: 0o600 });
    const result = await new Promise((resolve, reject) => {
      const child = spawn(join(sb, '.venv/bin/python'), [join(sb, 'scripts/scoped-provider-https-acceptance.py'), state],
        { cwd: sb, env: { ...process.env, PYTHONPATH: sb }, timeout: 60000 });
      let stdout = '', stderr = '';
      child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
      child.on('error', reject); child.on('close', code => {
        if (code !== 0) reject(new Error(`provider failed ${code}: ${stderr}`)); else resolve(JSON.parse(stdout));
      });
    });
    assert.equal(calls, mode === 'valid' ? 5 : mode === 'revoke_during_accept' ? 2 : 3);
    if (result.accepted) recordMemoryScopedOutboxAcceptance(f.database.authority, registered.outbox_id,
      dispatched.fence, dispatched.request, result.accepted, f.now);
    assert.equal(f.database.authority.db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
    assert.deepEqual(f.database.authority.db.prepare('PRAGMA foreign_key_check').all(), []);
    assert(!JSON.stringify(result).includes(cookie));
    results.push({ mode, ...result, authority_https_calls: calls, dispatch_attempts: 1, foreign_key_errors: 0 });
  } finally {
    gateway?.close(); if (tls) await new Promise(resolve => tls.close(resolve));
    await upstream.close();
    const writable = path => { const st = lstatSync(path); if (st.isSymbolicLink()) return;
      chmodSync(path, st.isDirectory() ? 0o700 : 0o600);
      if (st.isDirectory()) for (const name of readdirSync(path)) writable(join(path, name)); };
    writable(f.database.root); closeMemoryDatabase(f.database); rmSync(home.home, { recursive: true, force: true });
  }
}
console.log(JSON.stringify({ execution_surface: process.argv.includes('--cli') ? 'cli' : 'internal', transport: 'actual verified TLS, separate Python verifier children and live gateway sessions',
  identity_forwarder: 'fixture', clock: 'fixture', public_mcp_write: false, results }, null, 2));
