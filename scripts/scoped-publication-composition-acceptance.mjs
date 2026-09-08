import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const [buildArg, mode, statePath] = process.argv.slice(2);
const build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { publishMemoryScopedWriteRequest } = await load('src/memory-scoped-write-publication.js');
const { createFileMemoryWriteScopeResolver } = await load('src/memory-access-policy.js');
const { AuthorityDb } = await load('src/db.js');
function options(authority, state) {
  return { ...state, authority, clock: () => new Date(state.at),
    resolveWriteScope: createFileMemoryWriteScopeResolver(state.policyPath, state.providerInstanceId, () => state.session) };
}
if (mode) {
  const state = JSON.parse(readFileSync(statePath, 'utf8'));
  const db = new AuthorityDb(state.databasePath);
  try {
    try {
      if (mode === 'revoke-during-read') {
        const { MemoryScopedWriteSpool } = await load('src/memory-scoped-write-spool.js');
        const original = MemoryScopedWriteSpool.prototype.read;
        MemoryScopedWriteSpool.prototype.read = function (...args) {
          const result = original.apply(this, args);
          const policy = JSON.parse(readFileSync(state.policyPath, 'utf8'));
          writeFileSync(state.policyPath, JSON.stringify({ ...policy, agents: [] }), { mode: 0o600 });
          return result;
        };
      }
      const value = publishMemoryScopedWriteRequest(options(db, state));
      if (mode === 'crash') process.exit(73);
      process.stdout.write(JSON.stringify(value));
    } catch (error) { process.stdout.write(JSON.stringify({ error: error.code ?? error.message })); }
  } finally { db.close(); }
} else {
  const { scopedV3DispatchFixture } = await load('tests/fixtures/scoped-v3-dispatch.js');
  const { closeMemoryDatabase, memoryTableCounts } = await load('tests/fixtures/memory-candidate-store.js');
  const { proposeMemoryCandidateScope } = await load('src/memory-candidate-scope.js');
  const { stageMemoryScopeReview } = await load('src/memory-scope-review.js');
  const { ControlPlane, signCommandApproval } = await load('src/control-plane.js');
  const { localKey } = await load('tests/helpers.js');
  const { prepareMemoryScopedWriteRequest } = await load('src/memory-scoped-write-request.js');
  const f = await scopedV3DispatchFixture();
  try {
    const valid_until = new Date(f.now.getTime() + 30000).toISOString();
    const proposal = proposeMemoryCandidateScope(f.database.authority, f.candidate.candidate_id,
      { owner: 'principal:owner', projects: ['project:a'], policy_revision: 'policy:1', valid_until }, f.now);
    const command = stageMemoryScopeReview(f.database.authority, proposal, f.now);
    new ControlPlane(f.database.authority).decide(signCommandApproval({ schema_version: 1,
      receipt_id: `receipt:${command.request_id}`, request_id: command.request_id, decision: 'approve',
      command_digest: command.command_digest, signer_principal_id: 'principal:owner', authenticated_session_id: 'session:fixture',
      key_id: 'decision-test', algorithm: 'Ed25519', issued_at: f.now.toISOString(), not_before: f.now.toISOString(),
      expires_at: command.expires_at, nonce: command.request_id, max_uses: 1, status: 'issued' }, localKey(f.database.authority)), f.now);
    const spoolRoot = join(f.database.root, 'scoped'); mkdirSync(spoolRoot, { mode: 0o700 });
    const policyPath = join(f.database.root, 'write-policy.json');
    const policy = { schema_version: 3, provider_instance_id: 'provider:fixture', principal_id: 'principal:owner',
      policy_revision: 'policy:1', valid_from: f.now.toISOString(), valid_until,
      agents: [{ agent_id: 'agent:fixture', projects: ['project:a'], methods: ['sb_write_request'] }] };
    writeFileSync(policyPath, JSON.stringify(policy), { mode: 0o600 });
    const state = { databasePath: f.database.path, proposal, reviewRequestId: command.request_id, dispatch: f.dispatch,
      providerInstanceId: 'provider:fixture', spoolRoot, policyPath, at: f.now.toISOString(),
      session: { principal_id: 'principal:owner', agent_id: 'agent:fixture', session_id: 'session:fixture', expires_at: valid_until } };
    const stateFile = join(f.database.root, 'state.json'); writeFileSync(stateFile, JSON.stringify(state), { mode: 0o600 });
    const request = prepareMemoryScopedWriteRequest(f.database.authority, proposal, command.request_id, f.dispatch,
      options(f.database.authority, state).resolveWriteScope, state.providerInstanceId, f.now);
    const before = memoryTableCounts(f.database.authority);
    const child = action => spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, action, stateFile],
      { encoding: 'utf8', timeout: 30000 });
    const crash = child('crash'); assert.equal(crash.status, 73, crash.stderr + crash.stdout);
    const target = join(spoolRoot, request.idempotency_key.slice(-64) + '.v4.json');
    const bytes = readFileSync(target), inode = statSync(target).ino;
    const replay = child('replay'); assert.equal(replay.status, 0, replay.stderr);
    const value = JSON.parse(replay.stdout); assert.equal(value.created, false); assert.equal(value.request_id, request.request_id);
    assert.equal(value.writes_authorized, false); assert.equal(value.kind, 'prepared');
    const during = child('revoke-during-read'); assert.equal(during.status, 0, during.stderr);
    assert.equal(JSON.parse(during.stdout).error, 'MEMORY_SCOPED_WRITE_POLICY_INVALID');
    const revoked = child('revoked'); assert.equal(revoked.status, 0, revoked.stderr);
    assert.equal(JSON.parse(revoked.stdout).error, 'MEMORY_SCOPED_WRITE_POLICY_INVALID');
    assert.deepEqual(readFileSync(target), bytes); assert.equal(statSync(target).ino, inode);
    assert.deepEqual(memoryTableCounts(f.database.authority), before);
    console.log(JSON.stringify({ processes: 4, cli_fixture: true, crash_exit: 73, replay: { created: value.created,
      request_id: value.request_id, kind: value.kind, writes_authorized: false }, same_bytes_and_inode: true,
      policy_revocation_rejected: true, final_read_policy_revocation_rejected: true, database_counts_unchanged: true, provider_calls: 0, outbox_enqueued: false }, null, 2));
  } finally { closeMemoryDatabase(f.database); }
}
