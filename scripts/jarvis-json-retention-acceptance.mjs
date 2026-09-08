// Synthetic managed-file acceptance. Does not launch a model or use an operational DB/vault.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash, randomBytes} from 'node:crypto';
import {copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {isAbsolute, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const [build, mode, fixture] = process.argv.slice(2);
process.umask(0o077);
assert(build && isAbsolute(build), 'absolute isolated build directory required');
const fromBuild = name => import(pathToFileURL(join(build, name)).href);
const {AuthorityDb} = await fromBuild('src/db.js');
const {persistForbiddenContentIdentities, loadForbiddenContentIdentities} =
  await fromBuild('src/memory-forbidden-content.js');

if (mode === 'persist') {
  const input = JSON.parse(readFileSync(join(fixture, 'synthetic-input.json'), 'utf8'));
  const db = new AuthorityDb(join(fixture, 'authority.sqlite'));
  try {
    await db.migrate();
    // This fixture exercises identity storage without fabricating a completed purge receipt.
    db.db.pragma('foreign_keys=OFF');
    const identities = persistForbiddenContentIdentities(db, {
      purge_id: 'purge:synthetic-json-acceptance', material: [Buffer.from(input.memory)],
      observed_at: '2026-09-08T00:00:00.000Z',
    });
    process.stdout.write(JSON.stringify({pid: process.pid, identities: identities.length}));
  } finally { db.close(); }
} else if (mode === 'scan') {
  // Fresh process receives no original memory; it reads only persisted digests and managed roots.
  const {MemoryManagedSurfaceScanner} = await fromBuild('src/memory-managed-surface-scanner.js');
  const {providerSurfaceInventory, reingressGuardObservations} =
    await fromBuild('tests/fixtures/memory-surface-observations.js');
  const layout = JSON.parse(readFileSync(join(fixture, 'layout.json'), 'utf8'));
  const db = new AuthorityDb(join(fixture, 'authority.sqlite'));
  try {
    const identities = loadForbiddenContentIdentities(db).length;
    try {
      const result = await new MemoryManagedSurfaceScanner({authority: db, layout}).scan({
        provider: providerSurfaceInventory(), guards: reingressGuardObservations(),
      });
      process.stdout.write(JSON.stringify({pid: process.pid, identities, status: 'clean',
        surfaces: result.observed_surface_count}));
    } catch (error) {
      assert.equal(error.code, 'MEMORY_SURFACE_INVENTORY_INCOMPLETE');
      process.stdout.write(JSON.stringify({pid: process.pid, identities, status: 'rejected', code: error.code}));
    }
  } finally { db.close(); }
} else {
  assert.equal(mode, undefined, 'unexpected acceptance mode');
  const root = mkdtempSync(join(tmpdir(), 'sb-json-retention-'));
  const layout = Object.fromEntries(['spool', 'state', 'dist', 'backup', 'restore']
    .map(name => [`${name}_root`, join(root, name)]));
  for (const path of Object.values(layout)) mkdirSync(path, {mode: 0o700});
  const memory = `기억\n"${randomBytes(16).toString('hex')}"\\경로\t`;
  writeFileSync(join(root, 'synthetic-input.json'), JSON.stringify({memory}), {mode: 0o600});
  writeFileSync(join(root, 'layout.json'), JSON.stringify(layout), {mode: 0o600});
  const worker = phase => {
    const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, phase, root], {
      encoding: 'utf8', timeout: 60_000, maxBuffer: 1024 * 1024,
    });
    assert.equal(result.status, 0, `${phase} worker failed: ${result.stderr}`);
    return JSON.parse(result.stdout);
  };
  const persisted = worker('persist');
  assert.equal(persisted.identities, 3);
  const {countManagedMatches, disposeSensitiveManagedCopies} = await fromBuild('src/memory-compaction-external.js');
  const {default: Database} = await import(pathToFileURL(join(build, 'node_modules/better-sqlite3/lib/index.js')).href);
  const files = [join(layout.spool_root, 'prompt.txt'), join(layout.state_root, 'rollout.jsonl'),
    join(layout.backup_root, 'history.sqlite'), join(layout.restore_root, 'nested.json')];
  writeFileSync(files[0], memory, {mode: 0o600});
  writeFileSync(files[1], JSON.stringify({prompt: memory}) + '\n', {mode: 0o600});
  const nested = JSON.stringify({request: JSON.stringify({prompt: memory})});
  const sqlite = new Database(files[2]);
  try {
    sqlite.exec('CREATE TABLE history (prompt TEXT NOT NULL)');
    sqlite.prepare('INSERT INTO history VALUES (?)').run(nested);
  } finally { sqlite.close(); }
  writeFileSync(files[3], nested, {mode: 0o600});
  assert.equal(readFileSync(files[2]).includes(Buffer.from(memory)), false);
  const retained = join(root, 'synthetic-retained.sqlite');
  copyFileSync(files[2], retained);
  const unrelated = join(layout.state_root, 'keep.txt');
  writeFileSync(unrelated, 'unrelated retained fixture', {mode: 0o600});
  const initialScan = worker('scan');
  assert.equal(initialScan.status, 'rejected');
  const before = countManagedMatches(layout, [Buffer.from(memory)]);
  assert.equal(before, 4);
  const disposed = disposeSensitiveManagedCopies(layout, [Buffer.from(memory)]);
  assert.equal(disposed, 4);
  assert(files.every(path => !existsSync(path)));
  assert.equal(readFileSync(unrelated, 'utf8'), 'unrelated retained fixture');
  const cleanScan = worker('scan');
  assert.equal(cleanScan.status, 'clean');
  copyFileSync(retained, join(layout.restore_root, 'restored.sqlite'));
  const reingressScan = worker('scan');
  assert.equal(reingressScan.status, 'rejected');
  assert.equal(disposeSensitiveManagedCopies(layout, [Buffer.from(memory)]), 1);
  const finalScan = worker('scan');
  assert.equal(finalScan.status, 'clean');
  const processes = [persisted, initialScan, cleanScan, reingressScan, finalScan];
  assert.equal(new Set(processes.map(item => item.pid)).size, processes.length);
  const buildEvidence = readFileSync(join(build, 'acceptance-build.json'));
  const result = {status: 'passed', root, build, memory_digest: createHash('sha256').update(memory).digest('hex'),
    build_manifest_digest: createHash('sha256').update(buildEvidence).digest('hex'),
    processes, matched_before: before, disposed_files: disposed, restored_copy_rejected: true,
    unrelated_preserved: true, final_surfaces: finalScan.surfaces,
    operational_data_used: false, native_model_invoked: false, entire_fixture_plaintext_disposed: false,
    provider_and_guard_observations: 'deterministic fixtures; no provider purge receipt claimed'};
  writeFileSync(join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n', {mode: 0o600});
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}
