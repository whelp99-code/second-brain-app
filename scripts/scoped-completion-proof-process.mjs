import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const build = resolve(process.argv[2]), input = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const load = name => import(pathToFileURL(join(build, name)).href);
const { AuthorityDb } = await load('src/db.js');
const { readMemoryScopedCompletionProof } = await load('src/memory-scoped-completion-proof.js');
const authority = new AuthorityDb(input.database);
try {
  const result = readMemoryScopedCompletionProof({ authority, spoolRoot: input.spoolRoot,
    providerInstanceId: input.provider ?? 'provider:fixture' }, input.observation_id, new Date(input.at));
  console.log(JSON.stringify({ kind: result.kind, observation_id: result.observation_id,
    evidence_digest: result.evidence_digest, observed_at: result.observed_at, authorized_until: result.authorized_until,
    historical_authority_expired: Date.parse(input.at) >= Date.parse(result.authorized_until),
    record_count: result.evidence.artifact.record_ids.length }));
} catch (error) {
  console.log(JSON.stringify({ rejected: error.code ?? error.message }));
  process.exitCode = 1;
} finally { authority.close(); }
