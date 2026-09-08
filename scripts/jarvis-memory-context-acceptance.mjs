// Real SB MCP -> existing JARVIS adapter -> reference JSON, isolated synthetic data.
// No model delivery, session receipt, local suppression or project-scope acceptance.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {appendFileSync, mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

if (process.argv.length !== 3) throw new Error('Expected fresh JARVIS tsc output directory');
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const build = resolve(process.argv[2]);
const load = file => import(pathToFileURL(join(build, 'src', file)).href);
const {createSecondBrainReadAdapter} = await load('second-brain-adapter.js');
const {createSecondBrainTransport} = await load('second-brain-transport.js');
const {prepareMemoryReference} = await load('memory-reference-context.js');
const root = mkdtempSync(join(tmpdir(), 'sb-context-reference-'));
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
const provider = mode => execFileSync(python, ['-m', 'tests.fixtures.jarvis_memory_provider', mode, root],
  {cwd: sb, encoding: 'utf8'});
provider('init');
const applied = JSON.parse(provider('seed'));
writeFileSync(join(root, 'apply.json'), JSON.stringify(applied, null, 2));
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
const launcher = join(root, 'mcp');
writeFileSync(launcher, `#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m tests.fixtures.jarvis_memory_provider serve ${quote(root)}\n`, {mode: 0o700});
const transport = createSecondBrainTransport({launcherPath: launcher, configPath: join(root, 'config.toml'),
  contractPath: join(sb, '../Orca-JARVIS/contracts/second-brain-mcp-v1.json'),
  contractProfile: 'task32-schema4'});
let calls = 0;
const audited = {call: async (method, args) => {
  const result = await transport.call(method, args);
  appendFileSync(join(root, 'mcp.jsonl'), `${JSON.stringify({method, args, result})}\n`);
  calls++;
  return result;
}, close: () => transport.close(), restart: () => transport.restart(), diagnostics: () => transport.diagnostics()};
const now = new Date('2026-08-31T03:30:00.000Z');
try {
  const adapter = createSecondBrainReadAdapter({transport: audited, contract_profile: 'schema4', clock: () => now,
    budgets: {max_hits: 8, max_excerpt_bytes: 4096, max_total_bytes: 65536, max_page_bytes: 262144},
    max_age_ms: 86400000, expiry_ms: 172800000});
  const outcome = await adapter.search('ExampleAlpha');
  assert.equal(outcome.kind, 'current');
  assert(outcome.evidence.length > 0);
  const input = {outcome, query: 'ExampleAlpha', now,
    budgets: {max_records: 8, max_record_bytes: 4096, max_bytes: 16384}};
  const prepared = prepareMemoryReference(input);
  assert.equal(prepared.payload.state, 'available');
  assert.equal(prepared.payload.records.length, outcome.evidence.length);
  for (const item of prepared.payload.records) {
    const original = outcome.evidence.find(row => row.record?.record_id === item.record.record_id);
    assert(original);
    assert.equal(item.text, original.excerpt);
    assert.equal(item.text_digest, original.content_digest);
    assert.deepEqual(item.record, original.record);
    assert.equal(item.text_digest, `sha256:${createHash('sha256').update(item.text).digest('hex')}`);
  }
  assert.equal(prepared.bytes, Buffer.byteLength(prepared.serialized));
  assert(prepared.bytes <= input.budgets.max_bytes);
  assert.equal(prepared.tokens, null);
  assert.equal(prepared.payload.authority, 'none');
  assert.equal(prepared.payload.trust, 'untrusted');
  const none = await adapter.search('fixture-no-match-4db671');
  // A successful empty provider response is current with zero evidence in the
  // existing adapter; both that and an explicit no_data outcome mean no records.
  assert(none.kind === 'no_data' || (none.kind === 'current' && none.evidence.length === 0));
  const empty = prepareMemoryReference({...input, outcome: none});
  assert.equal(empty.payload.state, 'empty');
  assert.equal(empty.payload.records.length, 0);
  writeFileSync(join(root, 'adapter.json'), JSON.stringify(outcome, null, 2));
  writeFileSync(join(root, 'reference.json'), prepared.serialized);
  const result = {status: 'prepared_from_real_mcp', fixture_origin: 'synthetic', delivery_acceptance: false,
    root, build, calls, record_count: prepared.payload.records.length, bytes: prepared.bytes,
    tokens: prepared.tokens, digest: prepared.digest, generation: prepared.payload.generation,
    empty_state: empty.payload.state};
  writeFileSync(join(root, 'result.json'), JSON.stringify(result, null, 2));
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} finally { await transport.close(); }
