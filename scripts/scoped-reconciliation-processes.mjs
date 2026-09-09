import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, statePath, operation, worker] = process.argv.slice(2), build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { claimMemoryScopedReconciliation, requireMemoryScopedReconciliationLease, releaseMemoryScopedReconciliation } = await load('src/memory-scoped-reconciliation.js');
if (statePath) {
  const state = JSON.parse(readFileSync(statePath, 'utf8'));
  const { AuthorityDb } = await load('src/db.js'); const authority = new AuthorityDb(state.database);
  try {
    const options = { authority, spoolRoot: state.spoolRoot, providerInstanceId: 'provider:fixture' };
    if (operation === 'claim') {
      const result = claimMemoryScopedReconciliation(options, state.outbox, worker, new Date(state.at), 1000);
      console.log(JSON.stringify({ lease: result?.lease ?? null, request_digest: result?.request.request_digest ?? null }));
    } else {
      if (operation === 'release') releaseMemoryScopedReconciliation(authority, state.lease, new Date(state.at));
      else requireMemoryScopedReconciliationLease(authority, state.lease, new Date(state.at));
      console.log(JSON.stringify({ valid: true }));
    }
  } catch (error) { console.log(JSON.stringify({ rejected: error.code ?? error.message })); process.exitCode = 1; }
  finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
  const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch, recoverMemoryScopedOutboxDispatches } = await load('src/memory-scoped-outbox-worker.js');
  const f = await scopedOutboxFixture();
  try {
    const options = { ...f.options, roots: f.dispatch.roots }, r = registerMemoryScopedOutbox(f.options, f.claimed);
    const dispatchLease = claimMemoryScopedOutbox(options, r.outbox_id, 'worker:send', 1000);
    const dispatch = markMemoryScopedOutboxDispatch(options, dispatchLease, 30000);
    const at = new Date(Date.parse(dispatch.request.expires_at) + 1);
    recoverMemoryScopedOutboxDispatches(f.database.authority, at);
    const state = join(f.database.root, 'reconcile-state.json');
    const input = { database: f.database.path, spoolRoot: f.options.spoolRoot, outbox: r.outbox_id, at: at.toISOString() };
    writeFileSync(state, JSON.stringify(input), { mode: 0o600 });
    const run = async (op, who = 'worker:check', reject = false) => {
      try {
        const result = await promisify(execFile)(process.execPath, [fileURLToPath(import.meta.url), build, state, op, who],
          { timeout: 30000, maxBuffer: 32768 });
        assert.equal(reject, false); return JSON.parse(result.stdout);
      } catch (error) {
        if (!reject || error.code !== 1) throw error;
        const result = JSON.parse(error.stdout); assert.equal(result.rejected, 'MEMORY_OUTBOX_STALE_FENCE'); return result;
      }
    };
    const raced = await Promise.all([run('claim', 'worker:one'), run('claim', 'worker:two')]);
    const winners = raced.filter(x => x.lease !== null); assert.equal(winners.length, 1);
    assert.equal(winners[0].request_digest, dispatch.request.request_digest);
    const later = new Date(at.getTime() + 1000).toISOString();
    writeFileSync(state, JSON.stringify({ ...input, at: later }));
    const resumed = await run('claim', 'worker:resumed');
    assert.equal(resumed.lease.fence, winners[0].lease.fence + 1);
    assert.equal(resumed.lease.dispatch_fence, dispatchLease.fence);
    writeFileSync(state, JSON.stringify({ ...input, at: later, lease: winners[0].lease }));
    await run('release', 'worker:old', true);
    writeFileSync(state, JSON.stringify({ ...input, at: later, lease: resumed.lease }));
    await run('check'); await run('release'); await run('check', 'worker:released', true);
    assert.equal(f.database.authority.db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
    assert.deepEqual(f.database.authority.db.prepare('PRAGMA foreign_key_check').all(), []);
    console.log(JSON.stringify({ child_processes: 7, race_winners: 1, expired_lease_reclaimed: true,
      stale_release_rejected: true, released_lease_rejected: true, dispatch_fence: dispatchLease.fence,
      first_reconcile_fence: winners[0].lease.fence, second_reconcile_fence: resumed.lease.fence,
      dispatch_attempts: 1, foreign_key_errors: 0 }, null, 2));
  } finally { closeMemoryDatabase(f.database); }
}
