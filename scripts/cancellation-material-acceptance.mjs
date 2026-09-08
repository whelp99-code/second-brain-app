// Isolated actual-process acceptance; never points at an operational database.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [build, mode, metadataPath] = process.argv.slice(2);
const moduleAt = name => import(pathToFileURL(join(build, 'src', name + '.js')).href);
const { collectCancellationMaterial } = await moduleAt('memory-cancellation-material');
if (mode === 'capture') {
  const { cancellationDatabaseFixture } = await import(pathToFileURL(join(build, 'tests/fixtures/memory-cancellation-db.js')).href);
  const { MemoryCorrectionCancellationIssuer } = await moduleAt('memory-correction-cancellation-issuer');
  const f = await cancellationDatabaseFixture();
  const intent = new MemoryCorrectionCancellationIssuer(f.db, f.runtime.clock).issue(f.record.correction_id, f.runtime.signing_key_id, f.runtime.private_key);
  const at = f.runtime.clock().toISOString();
  f.db.db.prepare(`INSERT INTO memory_purge_jobs(purge_id,lane,lane_id,target_manifest_digest,scope_digest,tombstone_sequence,tombstone_set_root,state,created_at,updated_at)
    VALUES('purge:acceptance','correction',?,?,?,?,?,'pending',?,?)`).run(f.record.lane_id, intent.original_delegation.target_manifest_digest,
    intent.original_delegation.scope_digest, intent.tombstone.sequence, intent.tombstone.set_root, at, at);
  const material = await collectCancellationMaterial(f.db, f.runtime.spool_root, 'purge:acceptance', f.runtime.clock());
  assert.deepEqual(material.map(b => b.toString()), [f.staged.content]);
  material.forEach(b => b.fill(0));
  writeFileSync(metadataPath, JSON.stringify({ database: f.db.filename, spool: f.runtime.spool_root, at, capture_pid: process.pid }), { mode: 0o600 });
  process.exit(77); // Deliberately no close/checkpoint: test committed WAL recovery.
} else if (mode === 'dispose' || mode === 'resume') {
  const meta = JSON.parse(readFileSync(metadataPath, 'utf8'));
  const { AuthorityDb } = await moduleAt('db');
  const db = new AuthorityDb(meta.database); await db.migrate();
  const material = await collectCancellationMaterial(db, meta.spool, 'purge:acceptance', new Date(meta.at));
  assert.equal(db.db.prepare('SELECT count(*) AS n FROM memory_cancellation_material_checkpoints').get().n, 1);
  if (mode === 'dispose') {
    assert.equal(material.length, 1);
    const { disposeSensitiveManagedCopies, countManagedMatches } = await moduleAt('memory-compaction-external');
    const root = mkdtempSync('/var/tmp/cancellation-material-copies-');
    const layout = { spool_root: meta.spool, state_root: join(root, 'state'), dist_root: join(root, 'dist'), backup_root: join(root, 'backup'), restore_root: join(root, 'restore') };
    for (const value of Object.values(layout)) mkdirSync(value, { recursive: true, mode: 0o700 });
    writeFileSync(join(layout.state_root, 'copy.json'), JSON.stringify({ content: material[0].toString() }), { mode: 0o600 });
    writeFileSync(join(layout.state_root, 'unrelated.txt'), 'preserve unrelated content', { mode: 0o600 });
    assert.equal(countManagedMatches(layout, material), 2);
    const disposed = disposeSensitiveManagedCopies(layout, material);
    assert.equal(disposed, 2); assert.equal(countManagedMatches(layout, material), 0);
    assert.equal(readFileSync(join(layout.state_root, 'unrelated.txt'), 'utf8'), 'preserve unrelated content');
    meta.layout = layout; meta.disposed_files = disposed; meta.dispose_pid = process.pid;
    meta.after_disposal_matches = 0;
    writeFileSync(metadataPath, JSON.stringify(meta), { mode: 0o600 });
    material.forEach(b => b.fill(0));
    process.exit(77);
  }
  assert.equal(material.length, 0);
  const { MemoryManagedSurfaceScanner } = await moduleAt('memory-managed-surface-scanner');
  const local = new MemoryManagedSurfaceScanner({ authority: db, layout: meta.layout }).scanLocal();
  assert.equal(local.scope, 'jarvis_managed_local_observation');
  assert.equal(local.observed_surface_count, 20);
  assert(local.entries.every(entry => entry.owner === 'jarvis' && entry.match_count === 0 && entry.error_count === 0));
  meta.local_scan = { scope: local.scope, observed_surface_count: local.observed_surface_count, manifest_digest: local.manifest_digest };
  meta.resume_pid = process.pid; meta.checkpoint_rows = 1; meta.resume_material_count = 0;
  meta.cursor = db.db.prepare('SELECT * FROM memory_effect_dispatch_cursor').all();
  db.close();
  writeFileSync(metadataPath, JSON.stringify(meta, null, 2), { mode: 0o600 });
} else {
  const root = mkdtempSync('/var/tmp/cancellation-material-acceptance-');
  const metadata = join(root, 'result.json');
  for (const step of ['capture', 'dispose', 'resume']) {
    const result = spawnSync(process.execPath, [process.argv[1], build, step, metadata], {
      cwd: '/home/jm/orca/projects/Orca-JARVIS', env: { ...process.env, TMPDIR: '/var/tmp' }, encoding: 'utf8', timeout: 60000,
    });
    assert.equal(result.status, step === 'resume' ? 0 : 77, result.stderr || String(result.error));
  }
  console.log(metadata);
  console.log(readFileSync(metadata, 'utf8'));
}
