// Run from JARVIS cwd with an isolated TypeScript build path.
import assert from 'node:assert/strict';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const build = resolve(process.argv[2]);
const load = name => import(pathToFileURL(join(build, name)).href);
const { outboxFixture, claimAction } = await load('tests/fixtures/memory-outbox-fixture.js');
const { closeMemoryDatabase, memoryTableCounts } = await load('tests/fixtures/memory-candidate-store.js');
const { proposeMemoryCandidateScope } = await load('src/memory-candidate-scope.js');
const { stageMemoryScopeReview } = await load('src/memory-scope-review.js');
const { prepareMemoryScopedWriteWithPolicy } = await load('src/memory-scoped-write-policy.js');
const { ControlPlane, signCommandApproval } = await load('src/control-plane.js');
const { localKey } = await load('tests/helpers.js');
const f = await outboxFixture();
try {
  const authority = f.database.authority; const now = f.clock.now;
  const until = new Date(now.getTime() + 60000).toISOString();
  const proposal = proposeMemoryCandidateScope(authority, f.request.candidate_id,
    { owner: 'principal:owner', projects: ['project:a'], policy_revision: 'policy:1', valid_until: until }, now);
  const command = stageMemoryScopeReview(authority, proposal, now);
  const control = new ControlPlane(authority);
  control.decide(signCommandApproval({ schema_version: 1, receipt_id: `receipt:${command.request_id}`,
    request_id: command.request_id, decision: 'approve', command_digest: command.command_digest,
    signer_principal_id: 'principal:owner', authenticated_session_id: 'session:fixture',
    key_id: 'decision-test', algorithm: 'Ed25519', issued_at: now.toISOString(), not_before: now.toISOString(),
    expires_at: command.expires_at, nonce: command.request_id, max_uses: 1, status: 'issued' }, localKey(authority)), now);
  const dispatch = { dispatch_spool_digest: control.get(f.commandId).args.dispatch_spool_digest,
    roots: { review: join(f.database.root, 'candidate-review'), dispatch: join(f.database.root, 'candidate-dispatch') } };
  const scope = () => ({ principal_id: 'principal:owner', agent_id: 'agent:fixture', session_id: 'session:fixture',
    method: 'sb_write_request', projects: ['project:a'], policy_revision: 'policy:1', valid_until: until });
  const prepare = () => prepareMemoryScopedWriteWithPolicy(authority, proposal, command.request_id, dispatch, scope, now);
  assert.equal(prepare().writes_authorized, false);
  const saga = f.service.enqueue(claimAction(f)); const before = memoryTableCounts(authority);
  assert.throws(prepare, error => error.code === 'MEMORY_SCOPED_WRITE_ALREADY_DISPATCHED');
  assert.deepEqual(memoryTableCounts(authority), before);
  assert.equal(control.get(command.request_id).state, 'approved');
  assert.equal(authority.db.prepare('SELECT 1 FROM control_command_redemptions WHERE request_id=?').get(command.request_id), undefined);
  assert.equal(authority.db.prepare('SELECT state FROM memory_outbox WHERE outbox_id=?').get(saga.outbox_id).state, 'queued');
  assert.equal(f.writer.calls.length, 0);
  process.stdout.write(JSON.stringify({ fixture: true, before_enqueue_prepared: true,
    after_enqueue_error: 'MEMORY_SCOPED_WRITE_ALREADY_DISPATCHED', outbox_state: 'queued',
    review_state: 'approved', review_consumed: false, ledger_counts_unchanged: true,
    provider_calls: 0, scoped_write_completed: false }, null, 2) + '\n');
} finally { closeMemoryDatabase(f.database); }
