import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const input = JSON.parse(readFileSync(0, "utf8"));
const { createSecondBrainTransport } = await import(pathToFileURL(`${input.build}/src/second-brain-transport.js`));
const { requireCorrectionCancellationStatus } = await import(pathToFileURL(`${input.build}/src/memory-correction-cancellation-status.js`));
const pids = [];
const transport = createSecondBrainTransport({ launcherPath: input.launcher, configPath: input.config,
  contractPath: input.contract, contractProfile: "cancellation-schema6",
  execFile: (file, args, options) => { const child = execFile(file, args, options); pids.push(child.pid); return child; } });
try {
  const query = { intent_id: input.intent.intent_id, intent_digest: input.intent.intent_digest, read_fence: input.fence };
  const first = await transport.call("sb_cancellation_status", query);
  assert.equal(first.kind, "data");
  const verified = requireCorrectionCancellationStatus(first.value, input.intent, {
    now: new Date(), provider_keys: new Map([[input.key_id, input.public_key]]),
    tombstone_sequence: input.fence.tombstone_sequence, tombstone_set_root: input.fence.tombstone_set_root });
  assert.equal(verified.state, input.expected_state);
  if (input.expected_result) assert.deepEqual(verified.result, input.expected_result);
  await transport.restart();
  const replay = await transport.call("sb_cancellation_status", query);
  assert.deepEqual(replay, first);
  const denied = await transport.call("sb_cancellation_status", { ...query, read_fence: null });
  assert.deepEqual(denied, { kind: "error", code: "TOMBSTONE_FENCE_REQUIRED" });
  const missing = await transport.call("sb_cancellation_status", { ...query,
    intent_id: `memcancel:intent:v1:${"0".repeat(64)}`, intent_digest: `sha256:${"0".repeat(64)}` });
  assert.equal(missing.kind, "data");
  assert.equal(missing.value.state, "not_found");
  process.stdout.write(JSON.stringify({ node_pid: process.pid, mcp_pids: pids,
    state: verified.state, exact_result: Boolean(input.expected_result), replay_equal: true,
    missing_state: missing.value.state, unauthorized: denied.code }) + "\n");
} finally { await transport.close(); }
