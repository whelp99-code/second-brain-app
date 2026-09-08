// Characterize the existing JARVIS assembler; this is not a delivery acceptance.
// Usage: node scripts/context-boundary-audit.mjs <fresh-tsc-output-directory>
// The caller builds JARVIS separately. This probe never writes a vault or DB.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

if (process.argv.length !== 3) throw new Error('Expected a fresh JARVIS tsc output directory');
const root = resolve(process.argv[2]);
const load = file => import(pathToFileURL(join(root, file)).href);
const {assemblePersonalContext} = await load('src/context-assembler.js');
const {SECOND_BRAIN_TRUST} = await load('src/second-brain-adapter-types.js');
const {contextAssemblerInput} = await load('tests/fixtures/context-assembler-input.js');
const digest = value => `sha256:${createHash('sha256').update(value).digest('hex')}`;

function input(excerpt = '격리 검증용 기억 본문') {
  const value = structuredClone(contextAssemblerInput());
  value.memories[0].excerpt = excerpt;
  value.memories[0].digest = digest(excerpt);
  return value;
}
function summarize(value) {
  const result = assemblePersonalContext(value);
  return {state: result.payload.state, refs: result.payload.included_memory_refs,
    omissions: result.payload.omissions, bytes: Buffer.byteLength(JSON.stringify(result)),
    excerpt_present: JSON.stringify(result).includes(value.memories[0].excerpt)};
}

const confirmed = summarize(input());
assert.equal(confirmed.state, 'sufficient');
assert.equal(confirmed.refs.length, 1);
assert.equal(confirmed.excerpt_present, false);

const providerInput = input();
providerInput.memories[0].trust = SECOND_BRAIN_TRUST;
const provider = summarize(providerInput);
assert.equal(SECOND_BRAIN_TRUST, 'untrusted');
assert.equal(provider.state, 'insufficient');
assert.equal(provider.refs.length, 0);
assert(provider.omissions.some(value => value.startsWith('UNCONFIRMED_MEMORY:')));

const memoryOnlyInput = input();
memoryOnlyInput.observations = [];
const memoryOnly = summarize(memoryOnlyInput);
assert.equal(memoryOnly.state, 'insufficient');
assert(memoryOnly.omissions.some(value => value.startsWith('LIVE_LINUX_REQUIRED:')));

const multiline = ['\n', '\r\n', '\r', '\t'].map(separator => {
  let code;
  try { assemblePersonalContext(input(`첫 문장${separator}둘째 문장`)); }
  catch (error) {
    if (error?.code !== 'CONTEXT_ASSEMBLER_INPUT_INVALID') throw error;
    code = error.code;
  }
  assert.equal(code, 'CONTEXT_ASSEMBLER_INPUT_INVALID');
  return {separator, code};
});

const short = input('가');
const long = input('나'.repeat(1200));
for (const value of [short, long]) {
  value.budgets.max_excerpt_bytes = 4096;
  value.budgets.max_total_bytes = 8192;
}
const shortResult = summarize(short);
const longResult = summarize(long);
assert.equal(shortResult.state, 'sufficient');
assert.equal(longResult.state, 'sufficient');
assert.equal(shortResult.bytes, longResult.bytes);
assert.equal(longResult.excerpt_present, false);

const modules = ['context-assembler', 'context-assembler-input', 'context-assembler-sources',
  'context-assembler-budget', 'second-brain-adapter-types'];
process.stdout.write(`${JSON.stringify({
  schema_version: 1, status: 'boundary_gaps_reproduced', delivery_acceptance: false,
  fixture_origin: 'synthetic', build_root: root,
  module_sha256: Object.fromEntries(modules.map(name =>
    [name, digest(readFileSync(join(root, 'src', `${name}.js`)))])),
  confirmed, provider, memory_only: memoryOnly, multiline,
  snapshot_budget: {short_excerpt_bytes: 3, long_excerpt_bytes: 3600,
    short_snapshot_bytes: shortResult.bytes, long_snapshot_bytes: longResult.bytes,
    counts_delivered_body: false},
  limits: ['No provider RPC or model delivery', 'No project authorization acceptance',
    'No session deduplication or deletion/compaction acceptance',
    'A successful probe means the gaps were reproduced, not that B5 is complete'],
}, null, 2)}\n`);
