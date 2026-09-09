import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..'), build = resolve(process.argv[2]);
const load = p => import(pathToFileURL(join(build, p)).href);
const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch, recoverMemoryScopedOutboxDispatches } = await load('src/memory-scoped-outbox-worker.js');
const { claimMemoryScopedReconciliation, requireMemoryScopedReconciliationLease, releaseMemoryScopedReconciliation } = await load('src/memory-scoped-reconciliation.js');
const cli = process.argv[3] === '--cli';
const once = cli || process.argv[3] === '--once';
const results = [];
for (const state of ['pending', 'failed']) {
  const f = await scopedOutboxFixture();
  try {
    const r = registerMemoryScopedOutbox(f.options, f.claimed), options = { ...f.options, roots: f.dispatch.roots };
    const lease = claimMemoryScopedOutbox(options, r.outbox_id, 'worker:fixture', 1000);
    const dispatched = markMemoryScopedOutboxDispatch(options, lease, 30000);
    const late = new Date('2026-08-31T03:30:00.000Z');
    assert.equal(recoverMemoryScopedOutboxDispatches(f.database.authority, late), 1);
    const reconciliation = claimMemoryScopedReconciliation(options, r.outbox_id, 'worker:recover', late, 10000);
    if (once) releaseMemoryScopedReconciliation(f.database.authority, reconciliation.lease, late);
    const requestPath = join(f.database.root, 'request.json'), recoveryPath = join(f.database.root, 'recovery.json');
    writeFileSync(requestPath, JSON.stringify(dispatched.request), { mode: 0o600 });
    writeFileSync(recoveryPath, JSON.stringify({ database: f.database.path, spoolRoot: f.options.spoolRoot, lease: reconciliation.lease, once, cli }), { mode: 0o600 });
    const child = spawnSync(join(sb, '.venv/bin/python'), [join(sb, 'scripts/scoped-journal-client-acceptance.py'), build, state, requestPath, recoveryPath],
      { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: sb }, encoding: 'utf8', timeout: 120000 });
    assert.equal(child.status, 0, child.stderr + child.stdout);
    const recovered = JSON.parse(child.stdout), db = f.database.authority.db;
    assert.equal(recovered.recovered.acceptance.replayed, true);
    assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
    assert.equal(db.prepare("SELECT count(*) AS n FROM memory_reconciliation_events WHERE event_type='provider_accepted'").get().n, 1);
    assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'reconciling');
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
    if (once) assert.deepEqual(db.prepare('SELECT lease_owner,lease_expires_at FROM memory_outbox').get(), { lease_owner: null, lease_expires_at: null });
    else requireMemoryScopedReconciliationLease(f.database.authority, reconciliation.lease, late);
    results.push({ ...recovered, attempts: 1, acceptance_events: 1, foreign_key_errors: 0, outbox: 'reconciling' });
  } finally { closeMemoryDatabase(f.database); }
}
console.log(JSON.stringify(results, null, 2));
