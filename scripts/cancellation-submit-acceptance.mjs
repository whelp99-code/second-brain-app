import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import process from "node:process";
import { pathToFileURL } from "node:url";
const input = JSON.parse(readFileSync(0, "utf8"));
const moduleAt = name => import(pathToFileURL(`${input.build}/${name}.js`));
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
  process.stdout.write(JSON.stringify({ node_pid: process.pid, mcp_pids: pids, exit_after_provider_commit: exits[0].code, response_loss: lost,
    no_automatic_write_retry: true, exact_replay_after_restart: true, live_provider_revocation_rejected: true,
    intent_id: accepted.intent_id, original_transport_calls: f.writer.calls.length, spool_preserved: true, cursor }) + "\n");
} finally { await transport.close(); await f.close(); }
