// Actual TLS + gateway sessions + Python provider; forwarder identity is a fixture.
import assert from 'node:assert/strict';
import { acceptWrittenContext } from './scoped-written-context-acceptance.mjs';
import { createHash, createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, rmSync, chmodSync, lstatSync, readdirSync } from 'node:fs';
import { createServer as httpsServer, request as httpsRequest } from 'node:https';
import { request as httpRequest } from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const build = resolve(process.argv[2]);
const nativeWriter = process.env.SB_NATIVE_SCOPED_WRITE;
if (nativeWriter !== undefined && (nativeWriter !== 'claude' || !process.argv.includes('--mcp') || !process.argv.includes('--cli')))
  throw new Error('NATIVE_SCOPED_WRITE_REQUIRES_CLAUDE_PUBLIC_MCP_AND_CLI');
const load = path => import(pathToFileURL(join(build, path)).href);
const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
const { closeMemoryDatabase, memoryDatabase, insertMemoryVerification, memoryVerificationPayload } = await load('tests/fixtures/memory-candidate-store.js');
const { verifiedMemoryInput, memoryPolicy, MEMORY_NOW } = await load('tests/fixtures/memory-candidate-fixture.js');
const { execute: jarvisCli } = await load('src/cli.js');
const { readMemoryCandidate } = await load('src/memory-candidate-reader.js');
const { resolveSpooledDispatch } = await load('src/memory-outbox-dispatch-request.js');
const { ControlPlane, signCommandApproval } = await load('src/control-plane.js');
const { stageMemoryRememberDispatch } = await load('src/memory-remember-dispatch.js');
const { proposeMemoryCandidateScope } = await load('src/memory-candidate-scope.js');
const { stageMemoryScopeReview } = await load('src/memory-scope-review.js');
const { localKey } = await load('tests/helpers.js');
const { makePhoneHome, processUid, startFakeAuthority, FIXTURE_LOGIN, cookieFromSetCookie } = await load('tests/fixtures/phone-gateway-harness.js');
const { createPhoneGatewayServer, parsePhoneGatewayConfig } = await load('src/phone-gateway.js');
const { parsePhoneGatewayCli } = await load('src/phone-gateway-main.js');
const { openPhoneMemoryProviderCli } = await load('src/phone-memory-provider-cli.js');
const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch } = await load('src/memory-scoped-outbox-worker.js');
const { recordMemoryScopedOutboxAcceptance } = await load('src/memory-scoped-outbox-result.js');
const { canonicalize } = await load('src/canonical.js');
// `--work <file>` swaps only the candidate subject/statement for an already verified real work
// item. Identity, policy, transport, clock and every assertion below stay exactly as they are.
const workIndex = process.argv.indexOf('--work');
const work = workIndex > 0 ? JSON.parse(readFileSync(resolve(process.argv[workIndex + 1]), 'utf8')) : undefined;
async function realWorkOutboxFixture() {
  const database = await memoryDatabase();
  try {
    const now = new Date(MEMORY_NOW), statement = work.statement;
    const input = { ...verifiedMemoryInput({ statement, subject: work.subject,
      authority_id: work.authority_id, idempotency_key: work.idempotency_key }),
      schema_version: 2, body_profile: 'plain-text-v1' };
    insertMemoryVerification(database.authority, memoryVerificationPayload(input, {
      issued_at: now.toISOString(), not_before: now.toISOString(),
      expires_at: new Date(now.getTime() + 86400000).toISOString() }));
    const roots = { review: join(database.root, 'candidate-review'), dispatch: join(database.root, 'candidate-dispatch') };
    const inputFile = join(database.root, 'input.json'), policyFile = join(database.root, 'policy.json');
    writeFileSync(inputFile, JSON.stringify(input), { mode: 0o600 });
    writeFileSync(policyFile, JSON.stringify(memoryPolicy()), { mode: 0o600 });
    const classified = await jarvisCli(['memory', 'classify', inputFile, policyFile, '--db', database.path],
      { clock: () => now, memoryOutboxOptions: { candidate_review_spool_root: roots.review, candidate_dispatch_spool_root: roots.dispatch } });
    assert.equal(classified.ok, true, 'REAL_WORK_CLASSIFY_FAILED');
    const row = database.authority.db.prepare('SELECT candidate_id,dispatch_spool_digest FROM memory_candidate_dispatch_publications').get();
    assert.notEqual(row, undefined, 'REAL_WORK_DISPATCH_NOT_PUBLISHED');
    const candidate = readMemoryCandidate(database.authority.db, row.candidate_id);
    assert.notEqual(candidate, undefined, 'REAL_WORK_CANDIDATE_MISSING');
    const dispatch = { dispatch_spool_digest: row.dispatch_spool_digest, roots };
    const request = resolveSpooledDispatch({ ...dispatch, candidate_id: candidate.candidate_id, now });
    const control = new ControlPlane(database.authority);
    const approve = command => control.decide(signCommandApproval({ schema_version: 1,
      receipt_id: `receipt:${command.request_id}`, request_id: command.request_id, decision: 'approve',
      command_digest: command.command_digest, signer_principal_id: 'principal:owner',
      authenticated_session_id: 'session:fixture', key_id: 'decision-test', algorithm: 'Ed25519',
      issued_at: now.toISOString(), not_before: now.toISOString(), expires_at: command.expires_at,
      nonce: command.request_id, max_uses: 1, status: 'issued' }, localKey(database.authority)), now);
    const staged = stageMemoryRememberDispatch(database.authority, candidate.candidate_id, now,
      { candidate_dispatch_spool_root: roots.dispatch, candidate_review_spool_root: roots.review });
    approve(staged);
    const claimed = control.claim(staged.request_id, 'fixture:dispatch', now);
    const scope = { owner: 'principal:owner', projects: ['project:a'], policy_revision: 'policy:1',
      valid_until: new Date(now.getTime() + 30000).toISOString() };
    const proposal = proposeMemoryCandidateScope(database.authority, candidate.candidate_id, scope, now);
    const review = stageMemoryScopeReview(database.authority, proposal, now);
    approve(review);
    const spoolRoot = `${database.root}/scoped`;
    mkdirSync(spoolRoot, { mode: 0o700 });
    const options = { authority: database.authority, proposal, reviewRequestId: review.request_id,
      dispatch, providerInstanceId: 'provider:fixture', spoolRoot, clock: () => now,
      resolveWriteScope: () => ({ principal_id: scope.owner, agent_id: 'agent:fixture', session_id: 'session:fixture',
        provider_instance_id: 'provider:fixture', method: 'sb_write_request', projects: scope.projects,
        policy_revision: scope.policy_revision, valid_until: scope.valid_until }) };
    return { database, candidate, now, statement, request, dispatch, cli_published: true, options, claimed, review };
  } catch (error) {
    closeMemoryDatabase(database);
    throw error;
  }
}
/** Prove the real statement survived the whole lineage into provider-stored bytes. */
function verifyRealWorkBody(root, needle) {
  const pages = [];
  const walk = directory => {
    for (const name of readdirSync(directory)) {
      const full = join(directory, name), entry = lstatSync(full);
      if (entry.isSymbolicLink() || name === '.git') continue;
      if (entry.isDirectory()) { walk(full); continue; }
      if (entry.size > 1_000_000) continue;
      if (readFileSync(full, 'utf8').includes(needle)) pages.push(full.slice(root.length + 1));
    }
  };
  walk(root);
  assert(pages.length > 0, 'REAL_WORK_BODY_NOT_STORED');
  return { verified: true, needle, stored_in: pages.sort() };
}
const results = [];
for (const mode of work ? ['valid'] : ['valid', 'revoke_during_accept', 'revoke_before_execute', 'expire_before_execute']) {
  const f = work ? await realWorkOutboxFixture() : await scopedOutboxFixture(), home = makePhoneHome(), upstream = await startFakeAuthority();
  let gateway, tls, provider;
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
    const providerFields = { 'provider-verify-db': f.database.path, 'provider-verify-agent': 'agent:fixture',
      'provider-verify-provider': 'provider:fixture', 'provider-verify-policy': policyPath,
      'provider-verify-spool': f.options.spoolRoot, 'provider-verify-dispatch-spool': f.dispatch.roots.dispatch,
      'provider-verify-review-spool': f.dispatch.roots.review };
    const cli = parsePhoneGatewayCli(['--host', '127.0.0.1', '--port', '4176', '--upstream', 'http://127.0.0.1:4173',
      '--static-root', assets, '--env-file', home.envFile,
      ...Object.entries(providerFields).flatMap(([key, value]) => [`--${key}`, value])]);
    provider = await openPhoneMemoryProviderCli(cli.memoryProvider);
    assert.notEqual(provider.options.authority, f.database.authority);
    gateway = createPhoneGatewayServer({ host: '127.0.0.1', port: 0, upstream: upstream.origin, staticRoot: assets,
      config, now: () => at, audit: () => {}, memoryProviderVerifier: provider.options });
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
    writeFileSync(state, JSON.stringify({ credentials, mode, node: process.execPath, build,
      native_writer: process.env.SB_NATIVE_SCOPED_WRITE, admission_surface: process.argv.includes('--mcp') ? 'mcp' : 'internal', request: dispatched.request,
      execution_surface: process.argv.includes('--cli') ? 'cli' : 'internal',
      at: f.now.toISOString(), provider_root: join(f.database.root, 'provider') }), { mode: 0o600 });
    const result = await new Promise((resolve, reject) => {
      const child = spawn(join(sb, '.venv/bin/python'), [join(sb, 'scripts/scoped-provider-https-acceptance.py'), state],
        { cwd: sb, env: { ...process.env, PYTHONPATH: sb }, timeout: process.env.SB_NATIVE_SCOPED_WRITE ? 145000 : 60000 });
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
    const readback = mode === 'valid' && process.argv.includes('--readback')
      ? await acceptWrittenContext({ build, sb, f, home, upstream, config, assets, result,
          request: dispatched.request, outboxId: registered.outbox_id, writerCookie: cookie, query: work?.query,
          contentProfile: work && 'real verified work item content; fixture forwarding identity, policy and clock' }) : undefined;
    delete result.readback;
    const real_work = work && mode === 'valid'
      ? verifyRealWorkBody(join(f.database.root, 'provider'), work.assert_substring) : undefined;
    results.push({ mode, readback, real_work, ...result, authority_https_calls: calls, dispatch_attempts: 1, foreign_key_errors: 0 });
  } finally {
    gateway?.close(); provider?.close(); if (tls) await new Promise(resolve => tls.close(resolve));
    await upstream.close();
    const writable = path => { const st = lstatSync(path); if (st.isSymbolicLink()) return;
      chmodSync(path, st.isDirectory() ? 0o700 : 0o600);
      if (st.isDirectory()) for (const name of readdirSync(path)) writable(join(path, name)); };
    writable(f.database.root); closeMemoryDatabase(f.database); rmSync(home.home, { recursive: true, force: true });
  }
}
console.log(JSON.stringify({ gateway_configuration: 'CLI parser and independently owned existing authority connection', admission_surface: process.argv.includes('--mcp') ? 'mcp' : 'internal', execution_surface: process.argv.includes('--cli') ? 'cli' : 'internal', transport: 'actual verified TLS, separate Python verifier children and live gateway sessions',
  identity_forwarder: 'fixture', clock: 'fixture', content_profile: work ? 'real verified work item' : 'fixture',
  work_item: work?.evidence, public_mcp_write: process.argv.includes('--mcp'), results }, null, 2));
