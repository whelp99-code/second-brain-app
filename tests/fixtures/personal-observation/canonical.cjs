// Independent Node reference for the NFC, compact sorted-key K1 contract.
// --generate freezes synthetic vectors; normal execution only reads stdin.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const hash = value => createHash('sha256').update(value).digest('hex');
function canonical(value) {
  if (typeof value === 'string' && value.normalize('NFC') !== value) throw Error('NFC');
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw Error('integer');
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(k => canonical(k) + ':' + canonical(value[k])).join(',') + '}';
  }
  return JSON.stringify(value);
}
function vector(observation) {
  const identity = Object.fromEntries(['namespace', 'account_id', 'source_id', 'event_id', 'revision']
    .map(key => [key, observation[key]]));
  return {
    canonical_utf8: canonical(observation),
    canonical_sha256: hash(canonical(observation)),
    identity_utf8: canonical(identity),
    observation_id: 'sha256:' + hash('second-brain/personal-source-observation/v1\0' + canonical(identity)),
  };
}
if (process.argv.includes('--generate')) {
  const vectors = {};
  for (const [family, content, span] of [
    ['mail', 'Synthetic mail: tomorrow\n', {kind: 'byte', start: 0, end: 9}],
    ['kakao', '가상 대화: 내일 만나요\n', {kind: 'line', start: 0, end: 1}],
    ['audio', 'Synthetic transcript\n', {kind: 'audio_ms', start: 0, end: 1200}],
    ['session', 'Synthetic session decision\n', {kind: 'character', start: 0, end: 9}],
  ]) {
    const manifest = {
      emitter: family + '-fixture', account_id: 'synthetic-account', root: family + '://fixture',
      source_id: family, namespace: family === 'session'
        ? 'company:12345678-1234-1234-1234-123456789abc' : 'personal',
      source_policy_revision: 'policy-v1', external_processing: 'local_only',
    };
    const observation = {
      schema_version: 1, namespace: manifest.namespace, account_id: manifest.account_id,
      source_id: family, event_id: 'event-한글-1', revision: 1, content_sha256: hash(content),
      parser_version: family + '-v1', normalization_version: 'v1',
      occurred_at: '2026-09-23T00:00:00.000Z', source_updated_at: '2026-09-23T00:01:00.000Z',
      ingested_at: '2026-09-24T00:00:00.000Z', original_timestamp: '2026-09-23T09:00:00+09:00',
      source_timezone: 'Asia/Seoul', timestamp_precision: 'second', capture_mode: 'import',
      source_policy_revision: 'policy-v1', evidence_locator: family + '://fixture/item-1',
      evidence_spans: [span], supersedes_observation_id: null, source_deleted: false,
    };
    fs.writeFileSync(path.join(__dirname, family + '.json'), canonical({manifest, content_utf8: content, observation}) + '\n');
    vectors[family] = vector(observation);
  }
  fs.writeFileSync(path.join(__dirname, 'digest-vectors.json'), canonical(vectors) + '\n');
} else {
  process.stdout.write(JSON.stringify(vector(JSON.parse(fs.readFileSync(0, 'utf8')))) + '\n');
}
