import assert from "node:assert/strict";
import { execFile, execFileSync, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import process from "node:process";
import { pathToFileURL } from "node:url";
const input = JSON.parse(readFileSync(0, "utf8"));
const moduleAt = name => import(pathToFileURL(`${input.build}/${name}.js`));
if (process.argv.includes("--compact-actor") || process.argv.includes("--recover-actor")) {
  const { AuthorityDb } = await moduleAt("src/db");
  const { AuthorityDatabaseRuntime } = await moduleAt("src/authority-database-runtime");
  const { MemoryManagedSurfaceScanner } = await moduleAt("src/memory-managed-surface-scanner");
  const { MemoryAuthorityCompactor } = await moduleAt("src/memory-authority-compactor");
  const db = new AuthorityDb(input.database);
  const runtime = new AuthorityDatabaseRuntime(db, { registry_root: input.registry_root, watchdog_ms: 5000 });
  const compactor = new MemoryAuthorityCompactor({ runtime, layout: input.layout,
    scanner: new MemoryManagedSurfaceScanner({ authority: db, layout: input.layout }), clock: () => new Date() });
  if (input.rebuild_result && process.argv.includes("--compact-actor")) {
    // Actual process termination after material disposal, before entering physical swap.
    compactor.swap = async () => process.exit(77);
  }
  const receipt = process.argv.includes("--compact-actor") ? await compactor.compactCancellation(input.correction_id)
    : await compactor.recoverCancellation(input.correction_id);
  writeFileSync(1, JSON.stringify({ pid: process.pid, receipt }));
  process.exit(process.argv.includes("--compact-actor") ? 77 : 0);
}
if (process.argv.includes("--record-actor")) {
  const { AuthorityDb } = await moduleAt("src/db");
  const { MemoryCorrectionCancellationResultStore } = await moduleAt("src/memory-correction-cancellation-result-store");
  const db = new AuthorityDb(input.database);
  new MemoryCorrectionCancellationResultStore(db, () => new Date()).record(input.correction_id, input.result);
  process.exit(77);
}
const { cancellationDatabaseFixture } = await moduleAt("tests/fixtures/memory-cancellation-db");
const { MemoryCorrectionCancellationIssuer } = await moduleAt("src/memory-correction-cancellation-issuer");
const { submitDatabaseCorrectionCancellation } = await moduleAt("src/memory-correction-cancellation-submit");
const { createSecondBrainTransport } = await moduleAt("src/second-brain-transport");
const f = await cancellationDatabaseFixture("suppressed", input.resolved);
const pids = []; const exits = [];
const transport = createSecondBrainTransport({ launcherPath: input.launcher, configPath: input.config,
  contractPath: input.contract, contractProfile: "cancellation-submit-schema7",
  execFile: (file, args, options) => { const child = execFile(file, args, options); pids.push(child.pid); child.once("close", (code, signal) => exits.push({ pid: child.pid, code, signal })); return child; } });
try {
  const spool = readFileSync(f.spoolPath);
  const issuer = new MemoryCorrectionCancellationIssuer(f.db, f.runtime.clock);
  const submit = () => submitDatabaseCorrectionCancellation(issuer, f.record.correction_id,
    f.runtime.signing_key_id, f.runtime.private_key, transport, () => new Date("2026-08-28T12:00:02.000Z"));
  let lost;
  try { await submit(); throw new Error("expected lost response"); } catch (error) {
    assert.equal(error.disposition, "uncertain"); lost = error.code;
  }
  assert.equal(pids.length, 1, "a write must not auto-retry");
  assert.equal(exits[0]?.code, 77);
  await transport.restart();
  const accepted = await submit();
  assert.equal(accepted.state, "suppression_pending");
  await transport.restart();
  assert.deepEqual(await submit(), accepted);
  writeFileSync(input.config, readFileSync(input.config, "utf8").replace("revoked_jarvis_signing_key_ids = []",
    'revoked_jarvis_signing_key_ids = ["jarvis:fixture"]'));
  await assert.rejects(submit, /MEMORY_CANCELLATION_INTENT_INVALID/);
  assert.deepEqual(readFileSync(f.spoolPath), spool);
  const cursor = f.db.db.prepare("SELECT active_lane_id,accepted_through_sequence FROM memory_effect_dispatch_cursor").get();
  assert.deepEqual(cursor, { active_lane_id: null, accepted_through_sequence: 0 });
  let storedResult; let localCompaction; let localRecovery;
  if (input.record_result) {
    const result = JSON.parse(execFileSync(input.python, ["-m", "sb.cli", "apply-cancellation", "--intent-id", accepted.intent_id],
      { cwd: input.sb_root, env: { ...process.env, SB_CONFIG: input.execution_config, TMPDIR: "/var/tmp" }, encoding: "utf8" }));
    const { createPublicKey } = await import("node:crypto");
    const { registerMemoryProviderProofKey } = await moduleAt("src/memory-effect-delegation");
    const { AuthorityDb } = await moduleAt("src/db");
    const { MemoryCorrectionCancellationResultStore } = await moduleAt("src/memory-correction-cancellation-result-store");
    registerMemoryProviderProofKey(f.db, { key_id: result.signing_key_id, provider_instance_id: result.provider_instance_id,
      provider_release_sha: result.provider_release_sha, public_key_pem: createPublicKey(f.runtime.private_key).export({ type: "spki", format: "pem" }).toString(),
      valid_from: accepted.accepted_at, valid_until: "2027-09-01T00:00:00.000Z" }, new Date());
    const child = spawnSync(process.execPath, [process.argv[1], "--record-actor"], { encoding: "utf8",
      input: JSON.stringify({ build: input.build, database: f.database.path, correction_id: f.record.correction_id, result }) });
    assert.equal(child.status, 77, child.stderr);
    if (input.compact_result) {
      const actorInput = { rebuild_result: input.rebuild_result, build: input.build, database: f.database.path, correction_id: f.record.correction_id,
        registry_root: `${f.root}/registry`, layout: { spool_root: f.runtime.spool_root, state_root: `${f.root}/state`,
          dist_root: `${f.root}/dist`, backup_root: `${f.root}/backups`, restore_root: `${f.root}/restore` } };
      f.db.close();
      try {
        const compact = spawnSync(process.execPath, [process.argv[1], "--compact-actor"], { encoding: "utf8", input: JSON.stringify(actorInput), timeout: 60000 });
        assert.equal(compact.status, 77, compact.stderr);
        if (!input.rebuild_result) localCompaction = JSON.parse(compact.stdout).receipt;
        const recovered = spawnSync(process.execPath, [process.argv[1], "--recover-actor"], { encoding: "utf8", input: JSON.stringify(actorInput), timeout: 60000 });
        assert.equal(recovered.status, 0, recovered.stderr);
        if (input.rebuild_result) {
          localCompaction = JSON.parse(recovered.stdout).receipt;
          const replay = spawnSync(process.execPath, [process.argv[1], "--recover-actor"], { encoding: "utf8", input: JSON.stringify(actorInput), timeout: 60000 });
          assert.equal(replay.status, 0, replay.stderr);
          assert.deepEqual(JSON.parse(replay.stdout).receipt, localCompaction);
        } else assert.deepEqual(JSON.parse(recovered.stdout).receipt, localCompaction);
        localRecovery = { exit_after_local_record: input.rebuild_result ? undefined : compact.status,
          exit_before_swap: input.rebuild_result ? compact.status : undefined, exact_replay: true,
          compact_pid: compact.pid, recover_pid: JSON.parse(recovered.stdout).pid };
      } finally { f.db.reopen(); }
      assert.equal(localCompaction.scope, "jarvis_cancellation_local_compaction");
      assert.equal(localCompaction.result_digest, result.result_digest);
      assert.equal(localCompaction.local.observed_surface_count, 20);
      assert.equal(existsSync(f.spoolPath), false);

      assert.equal(f.db.db.prepare("SELECT count(*) AS n FROM memory_compaction_inputs").get().n, 0);
    }
    const reopened = new AuthorityDb(f.database.path);
    try {
      const results = new MemoryCorrectionCancellationResultStore(reopened, () => new Date());
      assert.deepEqual(results.get(f.record.correction_id), result);
      assert.deepEqual(results.record(f.record.correction_id, result), result);
      assert.equal(reopened.db.prepare("SELECT count(*) AS n FROM memory_correction_cancellation_results").get().n, 1);
      reopened.db.prepare("UPDATE memory_provider_proof_keys SET state='revoked' WHERE key_id=?").run(result.signing_key_id);
      assert.throws(() => results.get(f.record.correction_id), /MEMORY_CANCELLATION_RESULT_INVALID/);
    } finally { reopened.close(); }
    if (!input.compact_result) assert.deepEqual(readFileSync(f.spoolPath), spool);
    assert.deepEqual(f.db.db.prepare("SELECT active_lane_id,accepted_through_sequence FROM memory_effect_dispatch_cursor").get(), cursor);
    storedResult = { result_digest: result.result_digest, exit_after_record: child.status,
      exact_replay: true, result_rows: 1, current_revocation_rejected: true };
  }
  process.stdout.write(JSON.stringify({ local_recovery: localRecovery, local_compaction: localCompaction, stored_result: storedResult, node_pid: process.pid, mcp_pids: pids, exit_after_provider_commit: exits[0].code, response_loss: lost,
    no_automatic_write_retry: true, exact_replay_after_restart: true, live_provider_revocation_rejected: true,
    intent_id: accepted.intent_id, original_transport_calls: f.writer.calls.length, spool_preserved: !input.compact_result, cursor }) + "\n");
} finally { await transport.close(); await f.close(); }
