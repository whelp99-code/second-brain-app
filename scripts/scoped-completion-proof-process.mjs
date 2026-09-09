import assert from 'node:assert/strict';
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
  let settlementAuthority, currentRevocationRejected = false;
  if (input.authority_roots) {
    const { readMemoryScopedSettlementAuthority } = await load('src/memory-scoped-settlement-authority.js');
    const { ControlPlane } = await load('src/control-plane.js');
    const control = new ControlPlane(authority);
    control.recoverExpired(new Date(input.at));
    const options = { authority, spoolRoot: input.spoolRoot, providerInstanceId: input.provider ?? 'provider:fixture' };
    const check = () => readMemoryScopedSettlementAuthority(options, result.outbox_id, new Date(input.at), input.authority_roots);
    settlementAuthority = check();
    assert.equal(control.get(settlementAuthority.control_request_id).state, 'uncertain');
    const rollback = new Error('fixture rollback');
    try {
      authority.db.transaction(() => {
        authority.db.prepare('INSERT INTO authority_revocations(reference,reason,created_at) VALUES(?,?,?)')
          .run(settlementAuthority.control_request_id, 'fixture withdrawal', input.at);
        assert.throws(check, { code: 'SCOPED_SETTLEMENT_AUTHORITY_INVALID' });
        currentRevocationRejected = true;
        throw rollback;
      }).immediate();
    } catch (error) { if (error !== rollback) throw error; }
    assert.deepEqual(check(), settlementAuthority);
  }
  console.log(JSON.stringify({ settlement_authority: settlementAuthority, current_revocation_rejected: currentRevocationRejected, kind: result.kind, observation_id: result.observation_id,
    evidence_digest: result.evidence_digest, observed_at: result.observed_at, authorized_until: result.authorized_until,
    historical_authority_expired: Date.parse(input.at) >= Date.parse(result.authorized_until),
    record_count: result.evidence.artifact.record_ids.length }));
} catch (error) {
  console.log(JSON.stringify({ rejected: error.code ?? error.message }));
  process.exitCode = 1;
} finally { authority.close(); }
