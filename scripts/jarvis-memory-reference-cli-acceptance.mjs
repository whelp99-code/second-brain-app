// Opt-in actual CLI process -> production reader -> actual SB MCP, synthetic only.
import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {chmodSync, mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

if (process.argv.length !== 3) throw new Error('Expected fresh JARVIS build directory with contracts and migrations');
const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const build = resolve(process.argv[2]);
const load = file => import(pathToFileURL(join(build, file)).href);
const {memoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
const {memoryReadFenceFixture} = await load('tests/fixtures/memory-read-fence.js');
const {revokeMemoryEffectDelegationKey} = await load('src/memory-effect-delegation.js');
const {canonicalize} = await load('src/canonical.js');
const root = mkdtempSync(join(tmpdir(), 'sb-reference-cli-'));
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
for (const mode of ['init', 'seed']) execFileSync(python,
  ['-m', 'tests.fixtures.jarvis_memory_provider', mode, root], {cwd: sb, encoding: 'utf8'});
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
const launcher = join(root, 'mcp');
// Production provider clock, not the injected fixed clock in the seed helper.
writeFileSync(launcher, `#!/bin/sh\ncd ${quote(sb)}\nexec ${quote(python)} -m sb.mcp\n`, {mode: 0o700});
const database = await memoryDatabase();
const keyPath = join(database.root, 'memory-projection.key');
writeFileSync(keyPath, Buffer.alloc(32, 7), {mode: 0o600});
const {config} = memoryReadFenceFixture(database, new Date(Date.now() + 86400000).toISOString());
const env = {...process.env, TMPDIR: root, JARVIS_SECOND_BRAIN_LAUNCHER: launcher,
  JARVIS_SECOND_BRAIN_CONFIG: join(root, 'config.toml'), JARVIS_SECOND_BRAIN_CONTRACT_PROFILE: 'task32-schema4',
  JARVIS_MEMORY_PROVIDER_INSTANCE_ID: config.provider_instance_id,
  JARVIS_MEMORY_SIGNING_KEY_ID: config.signing_key_id, JARVIS_MEMORY_PRIVATE_KEY_PATH: config.private_key_path};
const sha = value => `sha256:${createHash('sha256').update(value).digest('hex')}`;
function databaseDigest() {
  const tables = database.authority.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
  const rows = tables.map(({name}) => {
    const escaped = String(name).replaceAll('"', '""');
    const values = database.authority.db.prepare(`SELECT * FROM "${escaped}"`).all().map(row => JSON.stringify(row)).sort();
    return {name, count: values.length, digest: sha(JSON.stringify(values))};
  });
  return sha(JSON.stringify(rows));
}
const runs = [];
function cli(label, query, maximum = '4000') {
  const result = spawnSync(process.execPath, [join(build, 'src/cli.js'), 'memory', 'context', query,
    '--db', database.path, '--limit', '8', '--max_bytes', maximum],
  {cwd: root, env, encoding: 'utf8', timeout: 45000});
  writeFileSync(join(root, `${label}.stdout`), result.stdout ?? '');
  writeFileSync(join(root, `${label}.stderr`), result.stderr ?? '');
  if (result.error) throw result.error;
  runs.push({label, status: result.status, stdout_bytes: Buffer.byteLength(result.stdout)});
  return result;
}
try {
  const before = databaseDigest();
  const found = cli('found', 'ExampleAlpha');
  assert.equal(found.status, 0, found.stderr);
  assert.equal(found.stderr, '');
  assert(Buffer.byteLength(found.stdout) <= 4000);
  const response = JSON.parse(found.stdout);
  assert.equal(response.ok, true);
  assert.equal(response.command, 'memory.context');
  assert.equal(response.context.state, 'available');
  assert.equal(response.context.records.length, 1);
  assert.equal(response.context_bytes, Buffer.byteLength(canonicalize(response.context)));
  assert.equal(response.context_digest, sha(canonicalize(response.context)));
  assert(response.provider_status_received_at <= response.context.prepared_at);
  for (const row of response.context.records) {
    assert(row.text.includes('ExampleAlpha'));
    assert.equal(row.text_digest, sha(row.text));
    assert.deepEqual(row.record.generation, response.context.generation);
  }
  const empty = cli('empty', 'no-such-reference-2d5a8d');
  assert.equal(empty.status, 0, empty.stderr);
  assert.equal(JSON.parse(empty.stdout).context.state, 'empty');
  const invalid = cli('invalid-budget', 'ExampleAlpha', '1');
  assert.equal(invalid.status, 2);
  assert.equal(invalid.stdout, '');
  assert.equal(JSON.parse(invalid.stderr).error.code, 'MEMORY_REFERENCE_BUDGET_IMPOSSIBLE');
  chmodSync(keyPath, 0o644);
  const privateKey = cli('unsafe-key', 'ExampleAlpha');
  chmodSync(keyPath, 0o600);
  assert.equal(privateKey.status, 2);
  assert.equal(privateKey.stdout, '');
  assert.equal(JSON.parse(privateKey.stderr).error.code, 'MEMORY_REFERENCE_KEY_UNAVAILABLE');
  const after = databaseDigest();
  assert.equal(after, before, 'CLI reads changed logical authority rows');
  revokeMemoryEffectDelegationKey(database.authority, config.signing_key_id);
  const revoked = cli('revoked-key', 'ExampleAlpha');
  assert.equal(revoked.status, 2);
  assert.equal(revoked.stdout, '');
  assert.equal(JSON.parse(revoked.stderr).error.code, 'MEMORY_READ_FENCE_KEY_UNAVAILABLE');
  const evidence = {status: 'actual_cli_passed', fixture_origin: 'synthetic', root, database_root: database.root,
    build, runs, records: response.context.records.length, context_bytes: response.context_bytes,
    stdout_bytes: Buffer.byteLength(found.stdout), read_database_unchanged: before === after,
    authority_rows_digest: before, context_digest: response.context_digest,
    provider_status_received_at: response.provider_status_received_at,
    model_delivery_acceptance: false, session_receipt_acceptance: false};
  writeFileSync(join(root, 'result.json'), JSON.stringify(evidence, null, 2));
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
} finally { database.authority.close(); }
