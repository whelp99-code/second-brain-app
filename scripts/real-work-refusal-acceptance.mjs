// A real verified work item must not be promotable into memory once the evidence
// behind it is absent, expired, not yet valid, contradicted, or no longer covers
// the sentence being stored. Positive control uses the same body, unmodified.
//
// Usage: node scripts/real-work-refusal-acceptance.mjs <jarvis-dist> <work-item.json>
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const build = resolve(process.argv[2]);
const work = JSON.parse(readFileSync(resolve(process.argv[3]), 'utf8'));
const load = path => import(pathToFileURL(join(build, path)).href);

const { memoryDatabase, closeMemoryDatabase, insertMemoryVerification, memoryVerificationPayload } =
  await load('tests/fixtures/memory-candidate-store.js');
const { verifiedMemoryInput, memoryPolicy, MEMORY_NOW, evidenceRef } =
  await load('tests/fixtures/memory-candidate-fixture.js');
const { execute } = await load('src/cli.js');

const now = new Date(MEMORY_NOW);
const DAY = 86_400_000;
const base = () => ({
  ...verifiedMemoryInput({ statement: work.statement, subject: work.subject,
    authority_id: work.authority_id, idempotency_key: work.idempotency_key }),
  schema_version: 2, body_profile: 'plain-text-v1' });

const window = kind => kind === 'expired'
  ? { issued_at: new Date(now.getTime() - 2 * DAY).toISOString(),
      not_before: new Date(now.getTime() - 2 * DAY).toISOString(),
      expires_at: new Date(now.getTime() - DAY).toISOString() }
  : kind === 'future'
  ? { issued_at: new Date(now.getTime() + DAY).toISOString(),
      not_before: new Date(now.getTime() + DAY).toISOString(),
      expires_at: new Date(now.getTime() + 2 * DAY).toISOString() }
  : { issued_at: now.toISOString(), not_before: now.toISOString(),
      expires_at: new Date(now.getTime() + DAY).toISOString() };

const rejectedSource = (inputClass, id, refKind) => ({
  class: inputClass, source_id: id, source_version: 'v1',
  references: [evidenceRef(refKind, `${id}-ref`)] });

// `verify` selects the evidence window installed before classification.
// `verifyFrom` installs evidence for a different body than the one classified.
const CASES = [
  { name: 'positive_control', expect: 'approved', verify: 'valid' },
  { name: 'no_verification', expect: 'authority_error', verify: 'none' },
  { name: 'expired_verification', expect: 'authority_error', verify: 'expired' },
  { name: 'not_yet_valid_verification', expect: 'authority_error', verify: 'future' },
  { name: 'statement_changed_after_verification', expect: 'authority_error', verify: 'valid',
    // The evidence covers the passing run; the stored sentence claims the failing one passed.
    retarget: input => ({ ...input, statement: work.statement.replace('exit 0', 'exit 1이지만 성공으로 간주') }) },
  { name: 'worker_assertion', expect: 'WORKER_ASSERTION_REJECTED', verify: 'none',
    mutate: input => ({ ...input, source: rejectedSource('worker_assertion', 'worker-1', 'unverified') }) },
  { name: 'model_assertion', expect: 'MODEL_AUTHORITY_REJECTED', verify: 'none',
    mutate: input => ({ ...input, source: rejectedSource('model_assertion', 'model-1', 'unverified') }) },
  { name: 'unverified_summary', expect: 'UNVERIFIED_SUMMARY_REJECTED', verify: 'none',
    mutate: input => ({ ...input, source: rejectedSource('unverified_summary', 'summary-1', 'unverified') }) },
  { name: 'raw_transcript', expect: 'RAW_TRANSCRIPT_REJECTED', verify: 'none',
    mutate: input => ({ ...input, source: rejectedSource('raw_transcript', 'transcript-1', 'transcript') }) },
  { name: 'open_conflict', expect: 'OPEN_CONFLICT', verify: 'valid',
    mutate: input => ({ ...input,
      conflict: { state: 'conflict', references: [evidenceRef('second_brain_conflict', 'conflict-1')] } }) },
];

const results = [];
for (const item of CASES) {
  const db = await memoryDatabase();
  try {
    const classified = item.mutate ? item.mutate(base()) : base();
    // Evidence is always issued for `classified`; a retarget then rewrites the body afterwards.
    if (item.verify !== 'none') {
      insertMemoryVerification(db.authority, memoryVerificationPayload(classified, window(item.verify)));
    }
    const input = item.retarget ? item.retarget(classified) : classified;
    const roots = { review: join(db.root, 'review'), dispatch: join(db.root, 'dispatch') };
    const inputFile = join(db.root, 'input.json'), policyFile = join(db.root, 'policy.json');
    writeFileSync(inputFile, JSON.stringify(input), { mode: 0o600 });
    writeFileSync(policyFile, JSON.stringify(memoryPolicy()), { mode: 0o600 });

    let outcome = null, failure = null;
    try {
      outcome = await execute(['memory', 'classify', inputFile, policyFile, '--db', db.path], {
        clock: () => now,
        memoryOutboxOptions: { candidate_review_spool_root: roots.review,
                               candidate_dispatch_spool_root: roots.dispatch } });
    } catch (error) { failure = String(error).replace(/^\w*Error: /, ''); }

    const published = db.authority.db
      .prepare('SELECT count(*) AS n FROM memory_candidate_dispatch_publications').get().n;
    const row = { case: item.name, expect: item.expect, published,
                  state: outcome?.candidate?.state ?? null,
                  reason: outcome?.candidate?.reason ?? null, error: failure };

    if (item.expect === 'approved') {
      assert.equal(failure, null, `${item.name}: positive control must not fail`);
      assert.notEqual(row.state, 'rejected', `${item.name}: positive control must not be rejected`);
      assert.equal(published, 1, `${item.name}: positive control must publish exactly one dispatch`);
    } else if (item.expect === 'authority_error') {
      assert.equal(row.state, null, `${item.name}: no candidate may be recorded`);
      assert.equal(failure, 'MEMORY_CANDIDATE_AUTHORITY_INVALID', `${item.name}: got ${failure}`);
      assert.equal(published, 0, `${item.name}: nothing may reach dispatch`);
    } else {
      assert.equal(failure, null, `${item.name}: a well-formed input must classify, not throw`);
      assert.equal(row.state, 'rejected', `${item.name}: must be recorded as rejected`);
      assert.equal(row.reason, item.expect, `${item.name}: got ${row.reason}`);
      assert.equal(published, 0, `${item.name}: nothing may reach dispatch`);
    }
    results.push(row);
  } finally { closeMemoryDatabase(db); }
}

const approved = results.filter(row => row.published === 1);
assert.equal(approved.length, 1, 'exactly one case may publish');
assert.equal(approved[0].case, 'positive_control');

console.log(JSON.stringify({
  jarvis_build: build,
  work_item: { subject: work.subject, authority_id: work.authority_id },
  clock: MEMORY_NOW,
  identity: 'fixture',
  content: 'real verified work item',
  cases: results.length,
  published_total: approved.length,
  results,
}, null, 2));
