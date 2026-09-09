import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(0, 'utf8')), build = resolve(process.argv[2]);
const load = path => import(pathToFileURL(join(build, path)).href);
const { createSecondBrainTransport } = await load('src/second-brain-transport.js');
const { parseSecondBrainScopedWriteAccepted } = await load('src/second-brain-scoped-write-result.js');
const transport = createSecondBrainTransport({ contractProfile: 'scoped-request-write-v1',
  launcherPath: input.launcher, configPath: input.config, contractPath: input.contract });
try {
  const outcome = await transport.call('sb_write_request', { request: input.request });
  if (outcome.kind === 'data') {
    const accepted = parseSecondBrainScopedWriteAccepted(outcome.value, input.request, new Date(input.at));
    assert.equal(accepted.kind, 'accepted');
  } else assert.equal(outcome.kind, 'error');
  console.log(JSON.stringify(outcome));
} finally { await transport.close(); }
