// Characterize frozen V1 using real Python and built JARVIS validators.
// No network, operational config, owner signing, or active vault is used.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const sb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
if (!process.argv[2]) throw new Error('Provide an isolated built JARVIS checkout path');
const jarvis = resolve(process.argv[2]);
const load = name => import(pathToFileURL(join(jarvis, 'dist/src', name)).href);
const {parseSecondBrainWriteRequest} = await load('second-brain-write-request.js');
const {memoryText} = await load('memory-candidate-values.js');
const python = process.env.SB_TEST_PYTHON ?? join(sb, '.venv/bin/python');
const fixture = JSON.parse(execFileSync(python, ['-m', 'scripts.remember-body-provider-probe'], {
  cwd: sb, encoding: 'utf8', timeout: 60_000, maxBuffer: 262_144,
}));
const rows = fixture.cases.map(row => {
  const before = JSON.stringify(row.request);
  const accepted = parseSecondBrainWriteRequest(row.request, new Date(row.request.created_at)) !== undefined;
  let candidate = false;
  try { memoryText(row.request.payload.content, 4096); candidate = true; } catch { /* Expected rejection. */ }
  assert.equal(accepted, row.jarvis_accepts, row.case);
  assert.equal(candidate, row.candidate_accepts, row.case);
  assert.equal(JSON.stringify(row.request), before, row.case);
  return {case: row.case, provider: row.provider, jarvis: accepted ? 'accepted' : 'rejected',
    candidate_text: candidate ? 'accepted' : 'rejected', exact_replay: row.exact_replay,
    input_unchanged: row.input_unchanged};
});
assert.equal(rows.length, 12);
console.log(JSON.stringify({kind: 'frozen-v1-characterization', cases: rows,
  multiline_enabled: false, operational_validation: false}, null, 2));
