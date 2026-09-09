import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const load = name => import(pathToFileURL(join(process.argv[2], name)).href);
const { AuthorityDb } = await load('src/db.js');
const { buildFreshAuthority } = await load('src/memory-authority-fresh-builder.js');
const source = new AuthorityDb(input.database);
try {
  const row = source.db.prepare('SELECT candidate_id,state FROM memory_outbox WHERE outbox_id=?').get(input.lease.outbox_id);
  assert.equal(row.state, 'settled');
  const path = join(dirname(input.database), 'scoped-compacted.sqlite');
  assert.equal(existsSync(path), false);
  const result = await buildFreshAuthority(source, path, { blocked_projections: [
    { kind: 'candidate', id: row.candidate_id, component_id: row.candidate_id }
  ], sensitive_material: [] });
  const fresh = new AuthorityDb(path);
  try {
    const tables = ['memory_scoped_settlements', 'memory_scoped_completion_observations', 'memory_scoped_outbox_bindings', 'memory_outbox', 'memory_candidates'];
    for (const table of tables) {
      assert.equal(fresh.db.prepare('SELECT count(*) AS n FROM "' + table + '"').get().n, 0);
      assert.equal(source.db.prepare('SELECT count(*) AS n FROM "' + table + '"').get().n, 1);
    }
    assert.deepEqual(fresh.db.prepare('PRAGMA foreign_key_check').all(), []);
    assert.deepEqual(fresh.db.prepare("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all(),
      source.db.prepare("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all());
    assert.deepEqual(fresh.db.prepare('SELECT count(*) AS n FROM control_command_requests').get(),
      source.db.prepare('SELECT count(*) AS n FROM control_command_requests').get());
    console.log(JSON.stringify({ reconstructed_tables: tables, target_rows: 0, source_rows_per_table: 1,
      foreign_key_errors: 0, integrity: result.integrity_check, triggers_restored: true,
      control_rows_preserved: true, source_generation: result.source_generation, result_generation: result.result_generation,
      physical_content_erasure_tested: false }));
  } finally { fresh.close(); }
} finally { source.close(); }
