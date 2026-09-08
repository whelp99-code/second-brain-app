import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, mode, statePath] = process.argv.slice(2);
const build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { readCurrentMemoryScopedOutbox } = await load('src/memory-scoped-outbox-reader.js');
if (mode) {
  const state = JSON.parse(readFileSync(statePath, 'utf8'));
  const { AuthorityDb } = await load('src/db.js');
  const authority = new AuthorityDb(state.database);
  try {
    if (mode === 'withdraw-during-read') {
      const { MemoryScopedWriteSpool } = await load('src/memory-scoped-write-spool.js');
      const read = MemoryScopedWriteSpool.prototype.read; let reads = 0;
      MemoryScopedWriteSpool.prototype.read = function(key, now) {
        const request = read.call(this, key, now);
        if (++reads === 2) writeFileSync(state.policy, 'null', { mode: 0o600 });
        return request;
      };
    }
    const request = readCurrentMemoryScopedOutbox({ authority, spoolRoot: state.spoolRoot, roots: state.roots,
      providerInstanceId: state.provider, clock: () => new Date(state.at),
      resolveWriteScope: () => JSON.parse(readFileSync(state.policy, 'utf8')) ?? undefined }, state.outbox);
    console.log(JSON.stringify({ outcome: 'read', request_id: request.request_id, request_digest: request.request_digest,
      source_request_id: request.source_request.request_id, content: request.preparation.payload.content }));
  } catch (error) {
    console.log(JSON.stringify({ outcome: 'denied', code: error.message }));
  } finally { authority.close(); }
} else {
  const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
  const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
  const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
  const f = await scopedOutboxFixture();
  try {
    const registered = registerMemoryScopedOutbox(f.options, f.claimed);
    const policy = join(f.database.root, 'current-policy.json');
    const policyBytes = JSON.stringify(f.options.resolveWriteScope(f.now));
    writeFileSync(policy, policyBytes, { mode: 0o600 });
    const state = join(f.database.root, 'reader-state.json');
    writeFileSync(state, JSON.stringify({ database: f.database.path, policy, spoolRoot: f.options.spoolRoot,
      roots: f.dispatch.roots, provider: f.options.providerInstanceId, at: f.now.toISOString(), outbox: registered.outbox_id }), { mode: 0o600 });
    const run = mode => {
      const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, mode, state],
        { encoding: 'utf8', timeout: 30000 });
      assert.equal(child.status, 0, child.stderr + child.stdout);
      return JSON.parse(child.stdout);
    };
    const first = run('read'); assert.equal(first.outcome, 'read');
    assert.equal(first.request_digest, registered.request_digest); assert.equal(first.content, f.statement);
    assert.equal(first.source_request_id, f.request.request_id);
    const during = run('withdraw-during-read'); assert.equal(during.outcome, 'denied');
    const after = run('read'); assert.equal(after.outcome, 'denied');
    writeFileSync(policy, policyBytes, { mode: 0o600 });
    f.database.authority.db.prepare('INSERT INTO authority_revocations(reference,reason,created_at) VALUES(?,?,?)')
      .run(f.candidate.source.verification_evidence_id, 'persisted withdrawal', f.now.toISOString());
    const source = run('read'); assert.equal(source.outcome, 'denied');
    assert.deepEqual(f.database.authority.db.prepare('SELECT state,request_profile FROM memory_outbox').all(),
      [{ state: 'queued', request_profile: 'scoped-v4' }]);
    assert.deepEqual(f.database.authority.db.prepare('PRAGMA foreign_key_check').all(), []);
    const { content, ...metadata } = first;
    console.log(JSON.stringify({ fixture_authority: true, child_processes: 4, provider_calls: 0,
      first: { ...metadata, exact_content: content === f.statement, content_bytes: Buffer.byteLength(content) },
      withdrawal_during_final_read: during, restarted_policy_denied: after, persisted_source_revocation: source,
      outbox_state: 'queued', foreign_key_errors: 0 }, null, 2));
  } finally { closeMemoryDatabase(f.database); }
}
