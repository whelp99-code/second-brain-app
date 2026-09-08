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
const f = await outboxFixture();
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
  const dispatch = { dispatch_spool_digest: control.get(f.commandId).args.dispatch_spool_digest,
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
  assert.equal(f.writer.calls.length, 0);
  process.stdout.write(JSON.stringify({ fixture: true, prior_request_schema: f.request.schema_version,
    private_spool_payload_equal: true, preparation_table_counts_unchanged: true,
    signed_scope_review_still_valid: true, revoked_source_preparation_rejected: true,
    provider_write_calls: f.writer.calls.length, scoped_write_completed: false }, null, 2) + "\n");
} finally { closeMemoryDatabase(f.database); }
