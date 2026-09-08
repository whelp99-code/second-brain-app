import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdirSync, lstatSync, readdirSync, chmodSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, statePath] = process.argv.slice(2), build = resolve(buildArg);
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const load = path => import(pathToFileURL(join(build, path)).href);
const { recordMemoryScopedOutboxAcceptance } = await load('src/memory-scoped-outbox-result.js');
if (statePath) {
  const s = JSON.parse(readFileSync(statePath, 'utf8'));
  const { AuthorityDb } = await load('src/db.js'); const authority = new AuthorityDb(s.database);
  try {
    const receipt = recordMemoryScopedOutboxAcceptance(authority, s.outbox, s.fence, s.request, s.accepted, new Date(s.at));
    if (s.crash_after) process.exit(73);
    console.log(JSON.stringify(receipt));
  } finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
  const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch, recoverMemoryScopedOutboxDispatches } = await load('src/memory-scoped-outbox-worker.js');
  const f = await scopedOutboxFixture();
  try {
    const r = registerMemoryScopedOutbox(f.options, f.claimed), options = { ...f.options, roots: f.dispatch.roots };
    const lease = claimMemoryScopedOutbox(options, r.outbox_id, 'worker:fixture', 1000);
    const dispatch = markMemoryScopedOutboxDispatch(options, lease, 30000);
    const providerRoot = join(f.database.root, 'provider'); mkdirSync(providerRoot, { mode: 0o700 });
    const requestFile = join(f.database.root, 'request.json');
    writeFileSync(requestFile, JSON.stringify(dispatch.request), { mode: 0o600 });
    const provider = mode => {
      const child = spawnSync(join(sb, '.venv/bin/python'), [join(sb, 'scripts/scoped-request-execution-acceptance.py'),
        '--worker', mode, providerRoot, requestFile], { cwd: sb, env: { ...process.env, PYTHONPATH: sb }, encoding: 'utf8', timeout: 60000 });
      assert.equal(child.status, 0, child.stderr + child.stdout); return JSON.parse(child.stdout);
    };
    const accepted = provider('accept'); assert.equal(accepted.kind, 'accepted');
    // Simulate acknowledgement delivery after the original worker lease and
    // request expired; there is no renewed provider write here.
    const late = new Date(f.now.getTime() + 60000);
    assert.equal(recoverMemoryScopedOutboxDispatches(f.database.authority, late), 1);
    const state = join(f.database.root, 'consumer.json');
    const input = { database: f.database.path, outbox: r.outbox_id, fence: lease.fence,
      request: dispatch.request, accepted, at: late.toISOString() };
    const consume = (value, expectedExit = 0) => {
      writeFileSync(state, JSON.stringify(value), { mode: 0o600 });
      const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, state], { encoding: 'utf8', timeout: 30000 });
      assert.equal(child.status, expectedExit, child.stderr + child.stdout);
      return expectedExit === 0 ? JSON.parse(child.stdout) : undefined;
    };
    consume({ ...input, crash_after: true }, 73);
    const first = consume(input); assert.equal(first.replayed, true);
    const executed = provider('execute'); assert.equal(executed.apply.state, 'proved');
    assert.equal(executed.proof.request_digest, dispatch.request.request_digest);
    const replayed = provider('accept'); assert.equal(replayed.replayed, true);
    assert.deepEqual(consume({ ...input, accepted: replayed }), { ...first, replayed: true });
    const db = f.database.authority.db;
    assert.equal(db.prepare('SELECT outcome FROM memory_outbox_attempts').get().outcome, 'accepted');
    assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'reconciling');
    assert.equal(db.prepare("SELECT count(*) AS n FROM memory_reconciliation_events WHERE event_type='provider_accepted'").get().n, 1);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
    console.log(JSON.stringify({ fixture_authority: true, python_processes: 3, consumer_processes: 3, acknowledgement_loss_exit: 73,
      transport: 'internal APIs; no public MCP V4 route', accepted, recorded: first,
      provider_state: executed.apply.state, jarvis_state: 'reconciling', acceptance_events: 1,
      foreign_key_errors: 0 }, null, 2));
  } finally {
    // Restore only this fixture tree's permissions; never follow sealed links.
    const writable = path => {
      const stat = lstatSync(path); if (stat.isSymbolicLink()) return;
      chmodSync(path, stat.isDirectory() ? 0o700 : 0o600);
      if (stat.isDirectory()) for (const name of readdirSync(path)) writable(join(path, name));
    };
    writable(f.database.root);
    closeMemoryDatabase(f.database);
  }
}
