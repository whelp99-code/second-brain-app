// A real native client submits an already prepared and reviewed fixture request.
// No authority, verification evidence or permission is manufactured by the model.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(0, 'utf8'));
const build = resolve(process.argv[2]);
const load = name => import(pathToFileURL(join(build, name)).href);
const { canonicalize } = await load('src/canonical.js');
const { parseSecondBrainScopedWriteAccepted } = await load('src/second-brain-scoped-write-result.js');
const root = join(input.root, 'native-writer'); mkdirSync(root, { mode: 0o700 });
const mcp = join(root, 'mcp.json');
writeFileSync(mcp, JSON.stringify({ mcpServers: { second_brain: { command: input.launcher,
  args: [], env: { SB_CONFIG: input.config, SB_MCP_CONTRACT_PROFILE: 'scoped-request-write-v1', TMPDIR: '/var/tmp' } } } }), { mode: 0o600 });
const tool = 'mcp__second_brain__sb_write_request';
const running = promisify(execFile)('claude', ['-p', '--output-format', 'stream-json', '--verbose',
  '--no-session-persistence', '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
  '--strict-mcp-config', '--mcp-config', mcp, '--tools', '', '--disable-slash-commands',
  '--permission-mode', 'dontAsk', '--allowedTools', tool, '--',
  `Submit this already prepared test request with ${tool} exactly once. Use its JSON as the request argument without changes. Do not retry on error. Report acceptance as acceptance, never as completed storage or verified task success. Request JSON: ${JSON.stringify(input.request)}`],
  { cwd: root, timeout: 90000, maxBuffer: 2 * 1024 * 1024 });
running.child.stdin.end();
const { stdout } = await running;
const events = stdout.split('\n').filter(Boolean).map(line => JSON.parse(line));
let called, accepted, completed = false;
for (const event of events) {
  for (const block of event.message?.content ?? []) {
    if (block.type === 'tool_use') {
      assert.equal(called, undefined); assert.equal(block.name, tool);
      assert.equal(canonicalize(block.input), canonicalize({ request: input.request }));
      called = block.id;
    }
    if (block.type === 'tool_result') {
      assert(called !== undefined); assert.equal(block.tool_use_id, called);
      assert.equal(accepted, undefined); assert.notEqual(block.is_error, true);
      const raw = typeof block.content === 'string' ? block.content : block.content.map(item => item.text ?? '').join('');
      const parsed = JSON.parse(raw);
      const value = parsed.kind === 'accepted' ? parsed : JSON.parse(parsed.content[0].text);
      accepted = parseSecondBrainScopedWriteAccepted(value, input.request, new Date(input.at));
    }
  }
  if (event.type === 'result') { assert.equal(event.subtype, 'success'); assert.notEqual(event.is_error, true); completed = true; }
}
assert(called !== undefined && accepted !== undefined && completed);
assert.equal(accepted.kind, 'accepted'); assert.equal(accepted.replayed, false);
const version = (await promisify(execFile)('claude', ['--version'])).stdout.trim();
console.log(JSON.stringify({ kind: 'data', value: accepted, native_writer: { client: version,
  tool_calls: 1, exact_prepared_arguments: true, replayed: false,
  scope: 'real native submission of a fixture-reviewed request; no new model-authored task verification' } }));
