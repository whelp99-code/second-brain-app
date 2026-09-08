import assert from 'node:assert/strict';
import { writeFileSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, mode, stateFile] = process.argv.slice(2);
const build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
const { AuthorityDb } = await load('src/db.js');
if (mode) {
  const state = JSON.parse(readFileSync(stateFile, 'utf8'));
  const authority = new AuthorityDb(state.path);
  try {
    if (mode === 'before-commit') {
      authority.db.function('crash_at_outbox', () => process.exit(74));
      authority.db.exec("CREATE TEMP TRIGGER crash_outbox BEFORE INSERT ON memory_outbox BEGIN SELECT crash_at_outbox(); END");
    }
    const registered = registerMemoryScopedOutbox({ ...state.options, authority,
      clock: () => new Date(state.at), resolveWriteScope: () => state.scope }, state.command);
    if (mode === 'after-commit') process.exit(73);
    const { MemoryOutboxStore } = await load('src/memory-outbox-store.js');
    const legacy = new MemoryOutboxStore(authority, 30000);
    assert.equal(legacy.claimDispatch('legacy-fixture', new Date(state.at), 1000), undefined);
    console.log(JSON.stringify(registered));
  } finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { ControlPlane } = await load('src/control-plane.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const outputs = [];
  for (const crashPoint of ['before-commit', 'after-commit']) {
    const f = await scopedOutboxFixture();
    try {
      const statePath = join(f.database.root, 'registration-state.json');
      const { authority: _authority, clock: _clock, resolveWriteScope: _resolve, ...options } = f.options;
      writeFileSync(statePath, JSON.stringify({ path: f.database.path, at: f.now.toISOString(), options,
        scope: f.options.resolveWriteScope(f.now), command: f.claimed }), { mode: 0o600 });
      const child = action => spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, action, statePath],
        { encoding: 'utf8', timeout: 30000 });
      const crash = child(crashPoint); assert.equal(crash.status, crashPoint === 'before-commit' ? 74 : 73, crash.stderr + crash.stdout);
      const counts = () => ({ outbox: f.database.authority.db.prepare('SELECT count(*) AS n FROM memory_outbox').get().n,
        bindings: f.database.authority.db.prepare('SELECT count(*) AS n FROM memory_scoped_outbox_bindings').get().n });
      const before = counts(); const expected = crashPoint === 'before-commit' ? 0 : 1;
      assert.deepEqual(before, { outbox: expected, bindings: expected });
      const recovered = child('recover'); assert.equal(recovered.status, 0, recovered.stderr + recovered.stdout);
      const result = JSON.parse(recovered.stdout); assert.equal(result.replayed, expected === 1);
      new ControlPlane(f.database.authority).recoverExpired(new Date(f.now.getTime() + 61000));
      const replayState = JSON.parse(readFileSync(statePath, 'utf8'));
      replayState.at = new Date(f.now.getTime() + 61000).toISOString();
      writeFileSync(statePath, JSON.stringify(replayState), { mode: 0o600 });
      const replay = child('replay'); assert.equal(replay.status, 0, replay.stderr + replay.stdout);
      assert.deepEqual(JSON.parse(replay.stdout), { ...result, replayed: true });
      assert.deepEqual(counts(), { outbox: 1, bindings: 1 });
      assert.deepEqual(f.database.authority.db.prepare('PRAGMA foreign_key_check').all(), []);
      outputs.push({ crash_point: crashPoint, exit_code: crash.status, rows_before: before, rows_after: counts(),
        registered: result, repeated_acknowledgement: true, replay_after_lease_recovery: true, legacy_worker_claims: 0, foreign_key_errors: 0 });
    } finally { closeMemoryDatabase(f.database); }
  }
  console.log(JSON.stringify({ fixture_authority: true, child_processes: 6, provider_calls: 0, scenarios: outputs }, null, 2));
}
