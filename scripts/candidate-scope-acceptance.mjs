import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

// Run from the JARVIS repo (fixture policy is relative to cwd) after compiling
// into an isolated outDir. Never opens an operational DB.
const [buildArg, mode, databasePath, proposalPath, at] = process.argv.slice(2);
const build = resolve(buildArg);
const load = path => import(pathToFileURL(join(build, path)).href);
const { proposeMemoryCandidateScope, validateMemoryCandidateScopeProposal } = await load("src/memory-candidate-scope.js");
const { AuthorityDb } = await load("src/db.js");
if (mode === "read") {
  const authority = new AuthorityDb(databasePath);
  try {
    try {
      const result = validateMemoryCandidateScopeProposal(authority, JSON.parse(readFileSync(proposalPath, "utf8")), new Date(at));
      process.stdout.write(JSON.stringify({ accepted: true, proposal_digest: result.proposal_digest, authorization: result.authorization }));
    } catch (error) {
      if (error.code !== "MEMORY_CANDIDATE_SCOPE_INVALID") throw error;
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
    const read = value => {
      writeFileSync(path, JSON.stringify(value), { mode: 0o600 });
      const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), build, "read", f.path, path, now.toISOString()],
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
    const projections = new MemoryProjectionAuthority(f.authority); projections.initialize(now);
    projections.quarantineUnresolved({ kind: "dashboard_projection", id: candidate.candidate_id, component_id: candidate.candidate_id }, now);
    const afterQuarantine = fixture.memoryTableCounts(f.authority);
    const quarantined = read(proposal);
    assert.equal(quarantined.accepted, false);
    assert.deepEqual(fixture.memoryTableCounts(f.authority), afterQuarantine);
    process.stdout.write(JSON.stringify({ schema_version: 1, fixture: true, independent_processes: 3,
      accepted, changed, quarantined, validation_table_counts_unchanged: true,
      scoped_write_completed: false }, null, 2) + "\n");
  } finally { fixture.closeMemoryDatabase(f); }
}
