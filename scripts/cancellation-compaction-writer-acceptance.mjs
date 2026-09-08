import assert from 'node:assert/strict';
import { watch, statSync, mkdtempSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [build] = process.argv.slice(2);
const fixture = await import(pathToFileURL(join(build, 'tests/fixtures/memory-cancellation-result.js')));
const inventory = await import(pathToFileURL(join(build, 'tests/fixtures/memory-surface-observations.js')));
const { AuthorityDb } = await import(pathToFileURL(join(build, 'src/db.js')));
const f = await fixture.cancellationResultFixture();
let watcher;
try {
  const before = statSync(f.db.filename).ino;
  let signaled = false;
  const attempted = new Promise(resolve => {
    watcher = watch(dirname(f.db.filename), (_event, filename) => {
      if (signaled || !filename?.endsWith('.fresh')) return;
      signaled = true;
      f.databaseRuntime.write(db => db.db.prepare("UPDATE memory_provider_proof_keys SET state='revoked'").run())
        .then(() => resolve({ outcome: 'accepted' }), error => resolve({ outcome: error.code }));
    });
  });
  // Provider/guard inventories are synthetic: this checks the actual local compactor only.
  const compacted = await f.runtime.compactor.compact({ lane: 'correction', lane_id: f.record.lane_id,
    target_manifest_digest: f.intent.original_delegation.target_manifest_digest,
    scope_digest: f.intent.original_delegation.scope_digest,
    tombstone: { sequence: f.intent.tombstone.sequence, set_root: f.intent.tombstone.set_root },
    provider_inventory: inventory.providerSurfaceInventory(), reingress_guards: inventory.reingressGuardObservations() });
  const attempt = await attempted;
  assert.deepEqual(attempt, { outcome: 'AUTHORITY_DATABASE_QUIESCING' });
  const after = statSync(f.db.filename).ino;
  assert.notEqual(before, after);
  await f.databaseRuntime.write(db => db.db.prepare("UPDATE memory_provider_proof_keys SET state='revoked'").run());
  const reread = new AuthorityDb(f.db.filename);
  let keys;
  try { keys = reread.db.prepare('SELECT state FROM memory_provider_proof_keys').all(); }
  finally { reread.close(); }
  assert.deepEqual(keys, [{ state: 'revoked' }]);
  const result = { pid: process.pid, watcher_observed_fresh_creation: signaled,
    concurrent_writer: attempt.outcome, inode_changed: before !== after,
    post_compaction_write_reopened: keys, integrity_check: compacted.integrity_check,
    provider_observations: 'synthetic fixture', scope: 'actual local compaction and runtime writer exclusion' };
  const output = join(mkdtempSync('/var/tmp/cancellation-compaction-writer-'), 'result.json');
  writeFileSync(output, JSON.stringify(result, null, 2), { mode: 0o600 });
  console.log(output); console.log(JSON.stringify(result));
} finally { watcher?.close(); await f.close(); }
