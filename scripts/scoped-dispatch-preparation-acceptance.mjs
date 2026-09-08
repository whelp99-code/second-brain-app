// Run from JARVIS cwd with an isolated TypeScript build directory argument.
import assert from "node:assert/strict";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
const build = resolve(process.argv[2]);
const load = name => import(pathToFileURL(join(build, name)).href);
const { outboxFixture } = await load("tests/fixtures/memory-outbox-fixture.js");
const { closeMemoryDatabase, memoryTableCounts } = await load("tests/fixtures/memory-candidate-store.js");
const { readMemoryCandidate } = await load("src/memory-candidate-reader.js");
const { proposeMemoryCandidateScope } = await load("src/memory-candidate-scope.js");
const { stageMemoryScopeReview, readApprovedMemoryScopeReview } = await load("src/memory-scope-review.js");
const { prepareMemoryScopedWriteFromDispatch } = await load("src/memory-scoped-write-payload.js");
const { ControlPlane, signCommandApproval } = await load("src/control-plane.js");
const { localKey } = await load("tests/helpers.js");
const version = process.argv[3] ?? "v1";
assert.ok(["v1", "v3"].includes(version));
const { scopedV3DispatchFixture } = await load("tests/fixtures/scoped-v3-dispatch.js");
const v3 = version === "v3" ? await scopedV3DispatchFixture() : undefined;
const f = v3 ? { ...v3, clock: { now: v3.now } } : await outboxFixture();
try {
  const authority = f.database.authority; const now = f.clock.now;
  const candidate = readMemoryCandidate(authority.db, f.request.candidate_id);
  const proposal = proposeMemoryCandidateScope(authority, candidate.candidate_id, {
    owner: "principal:owner", projects: ["project:shared-memory"], policy_revision: "policy:fixture",
    valid_until: new Date(now.getTime() + 60000).toISOString() }, now);
  const command = stageMemoryScopeReview(authority, proposal, now);
  const control = new ControlPlane(authority);
  control.decide(signCommandApproval({ schema_version: 1, receipt_id: `receipt:${command.request_id}`, request_id: command.request_id,
    decision: "approve", command_digest: command.command_digest, signer_principal_id: "principal:owner",
    authenticated_session_id: "scope-fixture", key_id: "decision-test", algorithm: "Ed25519",
    issued_at: now.toISOString(), not_before: now.toISOString(), expires_at: command.expires_at,
    nonce: command.request_id, max_uses: 1, status: "issued" }, localKey(authority)), now);
  const dispatch = f.dispatch ?? { dispatch_spool_digest: control.get(f.commandId).args.dispatch_spool_digest,
    roots: { review: join(f.database.root, "candidate-review"), dispatch: join(f.database.root, "candidate-dispatch") } };
  const before = memoryTableCounts(authority);
  const prepared = prepareMemoryScopedWriteFromDispatch(authority, proposal, command.request_id, dispatch, now);
  assert.equal(prepared.payload.content, f.request.payload.content);
  assert.deepEqual(memoryTableCounts(authority), before);
  authority.db.prepare("INSERT INTO authority_revocations(reference,reason,created_at) VALUES(?,?,?)")
    .run(candidate.source.verification_evidence_id, "withdraw fixture outcome", now.toISOString());
  const afterRevocation = memoryTableCounts(authority);
  assert.equal(readApprovedMemoryScopeReview(authority, proposal, command.request_id, now).writes_authorized, false);
  assert.throws(() => prepareMemoryScopedWriteFromDispatch(authority, proposal, command.request_id, dispatch, now),
    error => error.code === "MEMORY_SCOPED_SOURCE_AUTHORITY_INVALID");
  assert.deepEqual(memoryTableCounts(authority), afterRevocation);
  if (f.writer) assert.equal(f.writer.calls.length, 0);
  let expiredUnusedCleanup = null;
  if (process.argv.includes('--expire-unused')) {
    const { MemoryOutboxService } = await load('src/memory-outbox.js');
    const { MemoryCandidateReviewSpool } = await load('src/memory-candidate-review-spool.js');
    const spool = new MemoryCandidateReviewSpool(dispatch.roots.review);
    const beforeFiles = spool.paths().length;
    let providerCalls = 0;
    const unexpected = async () => { providerCalls++; throw new Error('unexpected provider call'); };
    const service = new MemoryOutboxService({ authority, clock: () => new Date(candidate.candidate_expires_at),
      candidate_review_spool_root: dispatch.roots.review, candidate_dispatch_spool_root: dispatch.roots.dispatch,
      writer: { write: unexpected }, reader: { search: unexpected, readPage: unexpected,
        recentChanges: unexpected, openConflicts: unexpected } });
    const cycle = await service.reconcileOnce('expiry-fixture', 1);
    assert.equal(cycle.cleanup_error, undefined);
    assert.equal(beforeFiles, 1); assert.equal(spool.paths().length, 0);
    assert.deepEqual(readMemoryCandidate(authority.db, candidate.candidate_id), candidate);
    assert.deepEqual(memoryTableCounts(authority), afterRevocation);
    assert.equal(providerCalls, 0);
    expiredUnusedCleanup = { before_files: beforeFiles, after_files: spool.paths().length,
      classification_unchanged: true, ledger_counts_unchanged: true, provider_calls: providerCalls };
  }
  process.stdout.write(JSON.stringify({ fixture: true, prior_request_schema: f.request.schema_version,
    cli_published: f.cli_published === true,
    ...(process.argv.includes("--include-preparation") ? { preparation: prepared } : {}),
    expiredUnusedCleanup,
    private_spool_payload_equal: true, preparation_table_counts_unchanged: true,
    signed_scope_review_still_valid: true, revoked_source_preparation_rejected: true,
    provider_write_calls: f.writer?.calls.length ?? null, scoped_write_completed: false,
    content_utf8_base64: Buffer.from(prepared.payload.content).toString("base64") }, null, 2) + "\n");
} finally { closeMemoryDatabase(f.database); }
