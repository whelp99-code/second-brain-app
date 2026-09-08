import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

// Run from the JARVIS repo (fixture policy is relative to cwd) after compiling
// into an isolated outDir. Never opens an operational DB.
const [buildArg, mode, databasePath, proposalPath, at, requestId] = process.argv.slice(2);
const build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { proposeMemoryCandidateScope, validateMemoryCandidateScopeProposal } = await load("src/memory-candidate-scope.js");
const { AuthorityDb } = await load("src/db.js");
const { stageMemoryScopeReview, readApprovedMemoryScopeReview } = await load("src/memory-scope-review.js");
if (mode === "read" || mode === "review" || mode === "execute") {
  const authority = new AuthorityDb(databasePath);
  try {
    try {
      const proposal = JSON.parse(readFileSync(proposalPath, "utf8"));
      if (mode === "execute") {
        const { ControlPlane } = await load("src/control-plane.js");
        const { ApprovedCommandExecutor } = await load("src/approved-executor.js");
        assert.notEqual(new ControlPlane(authority).nextApproved(new Date(at)), requestId);
        await new ApprovedCommandExecutor(authority).execute(requestId, "scope-review-acceptance", new Date(at));
        throw new Error("scope review was executed");
      } else if (mode === "review") {
        const result = readApprovedMemoryScopeReview(authority, proposal, requestId, new Date(at));
        process.stdout.write(JSON.stringify({ accepted: true, proposal_digest: result.proposal.proposal_digest,
          writes_authorized: result.writes_authorized }));
      } else {
        const result = validateMemoryCandidateScopeProposal(authority, proposal, new Date(at));
        process.stdout.write(JSON.stringify({ accepted: true, proposal_digest: result.proposal_digest, authorization: result.authorization }));
      }
    } catch (error) {
      if (!["MEMORY_CANDIDATE_SCOPE_INVALID", "MEMORY_SCOPE_REVIEW_INVALID", "CONTROL_ACTION_REVIEW_ONLY"].includes(error.code)) throw error;
      process.stdout.write(JSON.stringify({ accepted: false, code: error.code }));
    }
  } finally { authority.close(); }
} else {
  assert.equal(mode, undefined);
  const fixture = await load("tests/fixtures/memory-candidate-store.js");
  const { verifiedMemoryInput, MEMORY_NOW } = await load("tests/fixtures/memory-candidate-fixture.js");
  const { MemoryProjectionAuthority } = await load("src/memory-projection-authority.js");
  const f = await fixture.memoryDatabase();
  try {
    const input = verifiedMemoryInput(); fixture.seedMemoryAuthority(f.authority, input);
    const candidate = fixture.memoryCandidateStore(f.authority).classify(input);
    const now = new Date(MEMORY_NOW);
    const before = fixture.memoryTableCounts(f.authority);
    const proposal = proposeMemoryCandidateScope(f.authority, candidate.candidate_id, {
      owner: "principal:owner", projects: ["project:shared-memory"], policy_revision: "policy:fixture",
      valid_until: new Date(now.getTime() + 60000).toISOString(),
    }, now);
    const path = join(f.root, "proposal.json");
    const read = (value, action = "read", commandId) => {
      writeFileSync(path, JSON.stringify(value), { mode: 0o600 });
      const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, action, f.path, path, now.toISOString(), ...(commandId ? [commandId] : [])],
        { encoding: "utf8", timeout: 30000, maxBuffer: 65536 });
      assert.equal(child.error, undefined);
      assert.equal(child.status, 0, child.stderr);
      return JSON.parse(child.stdout);
    };
    const accepted = read(proposal);
    assert.deepEqual(accepted, { accepted: true, proposal_digest: proposal.proposal_digest, authorization: "not_granted" });
    const changed = read({ ...proposal, scope: { ...proposal.scope, projects: ["project:other"] } });
    assert.equal(changed.accepted, false);
    assert.deepEqual(fixture.memoryTableCounts(f.authority), before);
    const { ControlPlane, signCommandApproval } = await load("src/control-plane.js");
    const { localKey } = await load("tests/helpers.js");
    const command = stageMemoryScopeReview(f.authority, proposal, now);
    const control = new ControlPlane(f.authority);
    control.decide(signCommandApproval({ schema_version: 1, receipt_id: `receipt:${command.request_id}`, request_id: command.request_id,
      decision: "approve", command_digest: command.command_digest, signer_principal_id: "principal:owner",
      authenticated_session_id: "scope-review-fixture", key_id: "decision-test", algorithm: "Ed25519",
      issued_at: now.toISOString(), not_before: now.toISOString(), expires_at: command.expires_at,
      nonce: command.request_id, max_uses: 1, status: "issued" }, localKey(f.authority)), now);
    const approvedCounts = fixture.memoryTableCounts(f.authority);
    const { prepareMemoryScopedWriteIdentity } = await load("src/memory-scoped-write-identity.js");
    const scopedWriteIdentity = prepareMemoryScopedWriteIdentity(f.authority, proposal, command.request_id, now);
    const executorRefusal = read(proposal, "execute", command.request_id);
    assert.deepEqual(executorRefusal, { accepted: false, code: "CONTROL_ACTION_REVIEW_ONLY" });
    assert.deepEqual(fixture.memoryTableCounts(f.authority), approvedCounts);
    const signedReview = read(proposal, "review", command.request_id);
    assert.deepEqual(signedReview, { accepted: true, proposal_digest: proposal.proposal_digest, writes_authorized: false });
    const other = proposeMemoryCandidateScope(f.authority, candidate.candidate_id, {
      ...proposal.scope, projects: ["project:other"], valid_until: proposal.expires_at }, now);
    const otherScopeReview = read(other, "review", command.request_id);
    assert.equal(otherScopeReview.accepted, false);
    assert.deepEqual(fixture.memoryTableCounts(f.authority), approvedCounts);
    assert.equal(approvedCounts.memory_outbox, before.memory_outbox);
    control.cancel({ request_id: command.request_id, actor: "principal:owner", reason: "withdraw fixture scope",
      revoked_at: now.toISOString() }, now);
    const cancelledCounts = fixture.memoryTableCounts(f.authority);
    const withdrawnReview = read(proposal, "review", command.request_id);
    assert.equal(withdrawnReview.accepted, false);
    assert.deepEqual(fixture.memoryTableCounts(f.authority), cancelledCounts);
    const projections = new MemoryProjectionAuthority(f.authority); projections.initialize(now);
    projections.quarantineUnresolved({ kind: "dashboard_projection", id: candidate.candidate_id, component_id: candidate.candidate_id }, now);
    const afterQuarantine = fixture.memoryTableCounts(f.authority);
    const quarantined = read(proposal);
    assert.equal(quarantined.accepted, false);
    assert.deepEqual(fixture.memoryTableCounts(f.authority), afterQuarantine);
    process.stdout.write(JSON.stringify({ schema_version: 1, fixture: true, independent_processes: 7,
      accepted, changed, quarantined, validation_table_counts_unchanged: true,
      signedReview, otherScopeReview, withdrawnReview, approval_creates_no_memory_outbox: true,
      executorRefusal, execution_attempt_preserves_approval: true,
      scopedWriteIdentity,
      scoped_write_completed: false }, null, 2) + "\n");
  } finally { fixture.closeMemoryDatabase(f); }
}
