// Original JARVIS spent attempt -> provider write fixture -> read-only MCP recovery.
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..'), build = resolve(process.argv[2]);
const load = path => import(pathToFileURL(join(build, path)).href);
const { scopedOutboxFixture } = await load('tests/fixtures/scoped-outbox.js');
const { closeMemoryDatabase } = await load('tests/fixtures/memory-candidate-store.js');
const { registerMemoryScopedOutbox } = await load('src/memory-scoped-outbox.js');
const { claimMemoryScopedOutbox, markMemoryScopedOutboxDispatch, recoverMemoryScopedOutboxDispatches } = await load('src/memory-scoped-outbox-worker.js');
const { claimMemoryScopedReconciliation, requireMemoryScopedReconciliationLease, releaseMemoryScopedReconciliation } = await load('src/memory-scoped-reconciliation.js');
async function main() {
const cli = process.argv[3] === "--cli";
const once = cli || process.argv[3] === "--once";
const atomic = once || process.argv[3] === "--settle";
const f = await scopedOutboxFixture();
try {
  const r = registerMemoryScopedOutbox(f.options, f.claimed), options = { ...f.options, roots: f.dispatch.roots };
  const lease = claimMemoryScopedOutbox(options, r.outbox_id, 'worker:fixture', 1000);
  const dispatched = markMemoryScopedOutboxDispatch(options, lease, 30000);
  const requestPath = join(f.database.root, 'request.json');
  writeFileSync(requestPath, JSON.stringify(dispatched.request), { mode: 0o600 });
  const before = f.database.authority.db.prepare('SELECT accepted_result_json FROM memory_outbox_attempts').get();
  assert.equal(before.accepted_result_json, null);
  const late = new Date('2026-08-31T03:30:00.000Z');
  assert.equal(recoverMemoryScopedOutboxDispatches(f.database.authority, late), 1);
  const reconciliation = claimMemoryScopedReconciliation(options, r.outbox_id, 'worker:reconcile', late, 10000);
  assert.deepEqual(reconciliation.request, dispatched.request);
  writeFileSync(requestPath, JSON.stringify(reconciliation.request));
  requireMemoryScopedReconciliationLease(f.database.authority, reconciliation.lease, late);
  const observationPath = join(f.database.root, 'observation.json');
  writeFileSync(observationPath, JSON.stringify({ database: f.database.path,
    spoolRoot: f.options.spoolRoot, lease: reconciliation.lease, atomic, once, cli,
    roots: { candidate_dispatch_spool_root: f.options.dispatch.roots.dispatch,
      candidate_review_spool_root: f.options.dispatch.roots.review } }), { mode: 0o600 });
  const child = spawnSync(join(sb, '.venv/bin/python'), [join(sb, 'scripts/remembered-artifact-mcp-acceptance.py'),
    build, 'scoped-record-read-v5', requestPath, observationPath], { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: sb },
    encoding: 'utf8', timeout: 60000 });
  assert.equal(child.status, 0, child.stderr + child.stdout);
  const observed = JSON.parse(child.stdout);
  if (atomic) {
    assert.equal(observed.atomic_settlement.kind, 'memory_scoped_settled');
    assert.equal(observed.atomic_settlement.replayed, true);
    assert.equal(observed.commit_exit, 73);
    const db = f.database.authority.db;
    assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'settled');
    assert.equal(db.prepare('SELECT state FROM memory_candidates').get().state, 'settled');
    assert.equal(db.prepare('SELECT state FROM control_command_requests WHERE request_id=?').get(f.claimed.request_id).state, 'completed');
    assert.equal(db.prepare('SELECT count(*) AS n FROM memory_scoped_settlements').get().n, 1);
    assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
    const compact = spawnSync(process.execPath, [join(sb, 'scripts/scoped-compaction-process.mjs'), build, observationPath],
      { encoding: 'utf8', timeout: 30000 });
    assert.equal(compact.status, 0, compact.stderr + compact.stdout);
    const compaction = JSON.parse(compact.stdout);
    console.log(JSON.stringify({ compaction, ...observed, outbox: 'settled' , candidate: 'settled', control: 'completed',
      settlements: 1, attempts: 1, foreign_key_errors: 0 }, null, 2));
    return;
  }
  assert.equal(observed.recovered_without_local_acceptance, true);
  const accepted = observed.completion.status.acceptance;
  assert.equal(accepted.request_digest, dispatched.request.request_digest);
  const recoveryPath = join(f.database.root, 'recovery.json');
  const record = crashAfter => {
    writeFileSync(recoveryPath, JSON.stringify({ database: f.database.path, outbox: r.outbox_id, fence: lease.fence,
      request: dispatched.request, accepted, at: late.toISOString(), crash_after: crashAfter }), { mode: 0o600 });
    const result = spawnSync(process.execPath, [join(sb, 'scripts/scoped-outbox-result-acceptance.mjs'), build, recoveryPath],
      { encoding: 'utf8', timeout: 30000 });
    assert.equal(result.status, crashAfter ? 73 : 0, result.stderr + result.stdout);
    return crashAfter ? undefined : JSON.parse(result.stdout);
  };
  record(true); // Hard exit after the acceptance transaction committed.
  const first = record(false);
  assert.equal(first.replayed, true);
  assert.deepEqual(record(false), first);
  requireMemoryScopedReconciliationLease(f.database.authority, reconciliation.lease, late);
  releaseMemoryScopedReconciliation(f.database.authority, reconciliation.lease, late);
  const db = f.database.authority.db;
  assert.equal(db.prepare('SELECT count(*) AS n FROM memory_scoped_completion_observations').get().n, 1);
  assert.equal(observed.durable_observation.replayed, true);
  const proofInput = { database: f.database.path, spoolRoot: f.options.spoolRoot,
    authority_roots: { candidate_dispatch_spool_root: f.options.dispatch.roots.dispatch,
      candidate_review_spool_root: f.options.dispatch.roots.review },
    observation_id: observed.durable_observation.observation_id, at: new Date(late.getTime() + 60000).toISOString() };
  const proofPath = join(f.database.root, 'proof-reader.json');
  const proofRun = provider => {
    writeFileSync(proofPath, JSON.stringify({ ...proofInput, provider }), { mode: 0o600 });
    return spawnSync(process.execPath, [join(sb, 'scripts/scoped-completion-proof-process.mjs'), build, proofPath],
      { encoding: 'utf8', timeout: 30000 });
  };
  const proofRead = proofRun('provider:fixture');
  assert.equal(proofRead.status, 0, proofRead.stderr + proofRead.stdout);
  const reconstructed = JSON.parse(proofRead.stdout);
  assert.equal(reconstructed.kind, 'completion_evidence_consistent');
  assert.equal(reconstructed.evidence_digest, observed.durable_observation.evidence_digest);
  assert.equal(reconstructed.historical_authority_expired, true);
  assert.equal(reconstructed.settlement_authority.kind, 'spent_authority_currently_unrevoked');
  assert.equal(reconstructed.current_revocation_rejected, true);
  const wrongProvider = proofRun('provider:other');
  assert.equal(wrongProvider.status, 1);
  assert.equal(JSON.parse(wrongProvider.stdout).rejected, 'SCOPED_COMPLETION_EVIDENCE_INVALID');

  assert.equal(db.prepare('SELECT count(*) AS n FROM memory_outbox_attempts').get().n, 1);
  assert.equal(db.prepare("SELECT count(*) AS n FROM memory_reconciliation_events WHERE event_type='provider_accepted'").get().n, 1);
  assert.equal(db.prepare('SELECT state FROM memory_outbox').get().state, 'reconciling');
  assert.equal(claimMemoryScopedOutbox({ ...options, clock: () => late }, r.outbox_id, 'worker:repeat', 1000), undefined);
  assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
  console.log(JSON.stringify({ reconstructed, independent_proof_readers: 2, wrong_provider_rejected: true, durable_observations: 1, reconciliation_lease: reconciliation.lease, lease_preserved_across_acceptance_recovery: true, observed, acceptance_recorded: first, attempt_count: 1, acceptance_events: 1,
    record_commit_exit: 73, record_processes: 3, replay_idempotent: true, redispatch: false, jarvis_state: 'reconciling', foreign_key_errors: 0 }, null, 2));
} finally { closeMemoryDatabase(f.database); }

}
await main();
