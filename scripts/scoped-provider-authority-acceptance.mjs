// Cross-process fixture: actual authority DB and file policy; authenticated session is a fixture.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, lstatSync, readdirSync, chmodSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const self = fileURLToPath(import.meta.url), sb = resolve(dirname(self), '..');
const [buildArg, statePath, operation] = process.argv.slice(2), build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
if (statePath) {
  const s = JSON.parse(readFileSync(statePath, 'utf8'));
  const { AuthorityDb } = await load('src/db.js');
  const authority = new AuthorityDb(s.database);
  try {
    const value = JSON.parse(readFileSync(0, 'utf8'));
    if (operation === 'accept') {
      const { recordMemoryScopedOutboxAcceptance } = await load('src/memory-scoped-outbox-result.js');
      console.log(JSON.stringify(recordMemoryScopedOutboxAcceptance(authority, s.outbox, s.fence, s.request, value, new Date(s.at))));
    } else {
      const { createFileMemoryWriteScopeResolver } = await load('src/memory-access-policy.js');
      const { verifyMemoryScopedProviderWrite } = await load('src/memory-scoped-provider-authority.js');
      const resolveWriteScope = createFileMemoryWriteScopeResolver(s.policyPath, s.provider, () => s.session);
      console.log(JSON.stringify(verifyMemoryScopedProviderWrite({ authority, roots: s.roots, spoolRoot: s.spoolRoot,
        providerInstanceId: s.provider, clock: () => new Date(s.at), resolveWriteScope }, value)));
    }
  } catch (error) { console.log(JSON.stringify({ denied: error.code ?? error.message })); process.exitCode = 1; }
  finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
  const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch } = await load('src/memory-scoped-outbox-worker.js');
  const results = [];
  for (const mode of ['valid', 'revoke_during_accept', 'revoke_before_execute']) {
    const f = await scopedOutboxFixture();
    try {
      const r = registerMemoryScopedOutbox(f.options, f.claimed), options = { ...f.options, roots: f.dispatch.roots };
      const lease = claimMemoryScopedOutbox(options, r.outbox_id, 'worker:fixture', 1000);
      const dispatch = markMemoryScopedOutboxDispatch(options, lease, 30000);
      const policyPath = join(f.database.root, 'policy.json'), state = join(f.database.root, 'provider-state.json');
      writeFileSync(policyPath, JSON.stringify({ schema_version: 3, provider_instance_id: 'provider:fixture',
        principal_id: 'principal:owner', policy_revision: 'policy:1', valid_from: f.now.toISOString(),
        valid_until: dispatch.request.expires_at, agents: [{ agent_id: 'agent:fixture', projects: ['project:a'], methods: ['sb_write_request'] }] }), { mode: 0o600 });
      writeFileSync(state, JSON.stringify({ database: f.database.path, outbox: r.outbox_id, fence: dispatch.fence,
        request: dispatch.request, roots: f.dispatch.roots, spoolRoot: f.options.spoolRoot, policyPath,
        provider: 'provider:fixture', at: f.now.toISOString(), session: { principal_id: 'principal:owner',
          agent_id: 'agent:fixture', session_id: 'session:fixture', expires_at: dispatch.request.expires_at } }), { mode: 0o600 });
      const child = spawnSync(join(sb, '.venv/bin/python'), [join(sb, 'scripts/scoped-provider-authority-acceptance.py'),
        process.execPath, self, build, state, mode, join(f.database.root, 'provider')],
        { cwd: sb, env: { ...process.env, PYTHONPATH: sb }, encoding: 'utf8', timeout: 60000 });
      assert.equal(child.status, 0, child.stderr + child.stdout);
      const result = JSON.parse(child.stdout), db = f.database.authority.db;
      assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
      assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, mode === 'revoke_during_accept' ? 'dispatching' : 'reconciling');
      assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
      results.push({ ...result, dispatch_attempts: 1, jarvis_settled: false, foreign_key_errors: 0 });
    } finally {
      const writable = path => { const st = lstatSync(path); if (st.isSymbolicLink()) return;
        chmodSync(path, st.isDirectory() ? 0o700 : 0o600);
        if (st.isDirectory()) for (const name of readdirSync(path)) writable(join(path, name)); };
      writable(f.database.root); closeMemoryDatabase(f.database);
    }
  }
  console.log(JSON.stringify({ authenticated_session: 'fixture', authority: 'current JARVIS DB and file policy',
    transport: 'local child processes; internal provider APIs', public_v4_write: false, results }, null, 2));
}
