import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, statePath] = process.argv.slice(2), build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch, recoverMemoryScopedOutboxDispatches } = await load('src/memory-scoped-outbox-worker.js');
if (statePath) {
  const s = JSON.parse(readFileSync(statePath, 'utf8'));
  const { AuthorityDb } = await load('src/db.js'); const authority = new AuthorityDb(s.database);
  try {
    const options = { authority, roots: s.roots, spoolRoot: s.spoolRoot, providerInstanceId: s.provider,
      clock: () => new Date(s.at), resolveWriteScope: () => s.scope };
    if (s.mode === 'recover') {
      console.log(JSON.stringify({ outcome: 'recovered', count: recoverMemoryScopedOutboxDispatches(authority, new Date(s.at)) }));
    } else if (s.mode === 'claim') {
      const lease = claimMemoryScopedOutbox(options, s.outbox, s.worker, 1000);
      console.log(JSON.stringify({ outcome: lease ? 'claimed' : 'unavailable', lease }));
    } else {
      if (s.mode === 'crash-before') {
        authority.db.function('crash_attempt', () => process.exit(74));
        authority.db.exec('CREATE TEMP TRIGGER crash_attempt BEFORE INSERT ON memory_outbox_attempts BEGIN SELECT crash_attempt(); END');
      }
      const dispatch = markMemoryScopedOutboxDispatch(options, s.lease, 30000);
      if (s.mode === 'crash-after') process.exit(73);
      console.log(JSON.stringify({ outcome: 'marked', attempt_id: dispatch.attempt_id, request_digest: dispatch.request.request_digest }));
    }
  } catch (error) { console.log(JSON.stringify({ outcome: 'denied', code: error.message })); }
  finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
  let processes = 0; const scenarios = [];
  for (const scenario of ['fence-and-ack-loss', 'transaction-crash']) {
    const f = await scopedOutboxFixture();
    try {
      const r = registerMemoryScopedOutbox(f.options, f.claimed), db = f.database.authority.db;
      const file = join(f.database.root, 'worker-state.json');
      const base = { database: f.database.path, roots: f.dispatch.roots, spoolRoot: f.options.spoolRoot,
        provider: f.options.providerInstanceId, scope: f.options.resolveWriteScope(f.now), outbox: r.outbox_id, at: f.now.toISOString() };
      const run = (patch, exit = 0) => {
        writeFileSync(file, JSON.stringify({ ...base, ...patch }), { mode: 0o600 });
        const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, file], { encoding: 'utf8', timeout: 30000 });
        processes++; assert.equal(child.status, exit, child.stdout + child.stderr);
        return exit === 0 ? JSON.parse(child.stdout) : { exit_code: exit };
      };
      const first = run({ mode: 'claim', worker: 'worker:a' }); assert.equal(first.outcome, 'claimed');
      if (scenario === 'fence-and-ack-loss') {
        assert.equal(run({ mode: 'claim', worker: 'worker:b' }).outcome, 'unavailable');
        const at = new Date(f.now.getTime() + 1000).toISOString();
        const second = run({ mode: 'claim', worker: 'worker:b', at }); assert.equal(second.lease.fence, 2);
        assert.equal(run({ mode: 'mark', lease: first.lease, at }).code, 'MEMORY_OUTBOX_STALE_FENCE');
        run({ mode: 'crash-after', lease: second.lease, at }, 73);
        assert.equal(run({ mode: 'mark', lease: second.lease, at }).code, 'MEMORY_OUTBOX_STALE_FENCE');
      } else {
        run({ mode: 'crash-before', lease: first.lease }, 74);
        assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'claimed');
        assert.equal(db.prepare('SELECT state FROM memory_candidates').get().state, 'queued');
        assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 0);
        assert.equal(run({ mode: 'mark', lease: first.lease }).request_digest, r.request_digest);
      }
      assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
      assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'dispatching');
      assert.equal(db.prepare('SELECT state FROM memory_candidates').get().state, 'accepted_unsettled');
      assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
      const expiredAt = new Date(f.now.getTime() + 60000).toISOString();
      assert.equal(run({ mode: 'recover', at: expiredAt }).count, 1);
      assert.equal(run({ mode: 'claim', worker: 'worker:c', at: expiredAt }).outcome, 'unavailable');
      assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'reconciling');
      assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
      scenarios.push({ scenario, attempts: 1, outbox_state: 'reconciling', candidate_state: 'accepted_unsettled', foreign_key_errors: 0, re_dispatch_claims: 0 });
    } finally { closeMemoryDatabase(f.database); }
  }
  console.log(JSON.stringify({ fixture_authority: true, child_processes: processes, provider_calls: 0, scenarios }, null, 2));
}
