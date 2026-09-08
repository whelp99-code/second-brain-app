// Isolated acceptance consumer: expectations come from the issued request, never its response.
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
const base = pathToFileURL(process.argv[2] + '/');
const { canonicalize } = await import(new URL('src/canonical.js', base));
const { parseScopedSecondBrainResponse } = await import(new URL('src/second-brain-scoped-read.js', base));
const hash = (domain, value) => 'sha256:' + createHash('sha256').update(domain + canonicalize(value)).digest('hex');
const { createSecondBrainTransport } = await import(new URL('src/second-brain-transport.js', base));
const transport = createSecondBrainTransport({ contractProfile: 'scoped-record-read-v1',
  contractPath: data.transport.contract, launcherPath: data.transport.launcher, configPath: data.transport.config });
const results = [];
try {
for (let index = 0; index < data.inputs.length; index++) {
  const { response: prior, bundle, request } = data.inputs[index];
  if (index === 2) await transport.restart();
  const outcome = await transport.call(request.method, { ...request.arguments, ...bundle });
  if (outcome.kind !== 'data') throw new Error('transport did not return data: ' + JSON.stringify(outcome));
  const response = outcome.value;
  if (canonicalize(response) !== canonicalize(prior)) throw new Error('transport response differs');
  const expected = { method: request.method, page_id: request.arguments.id, limit: request.arguments.limit ?? 64,
    request_digest: hash('orca-jarvis/memory-access-request/v1\0', request),
    access_claim_digest: hash('orca-jarvis/memory-access-claim-binding/v1\0', bundle.access_claim),
    authorized_until: bundle.access_claim.expires_at, fence: bundle.read_fence, checked_at: new Date('2026-09-09T00:00:00.000Z'),
    budgets: { max_hits: 50, max_excerpt_bytes: 8192, max_total_bytes: 1000000, max_page_bytes: 100000 },
    max_age_ms: 86400000, expiry_ms: 172800000 };
  const parsed = parseScopedSecondBrainResponse(response, expected);
  let denied = 0;
  for (const changed of [{ ...response, request_digest: 'sha256:' + '0'.repeat(64) },
    { ...response, access_claim_digest: 'sha256:' + '0'.repeat(64) },
    request.method === 'sb_read_page'
      ? { ...response, records: response.records.map(row => ({ ...row, record_text: 'tampered' })) }
      : { ...response, results: response.results.map(row => ({ ...row, record: { ...row.record, record_text: 'tampered' } })) }]) {
    try { parseScopedSecondBrainResponse(changed, expected); }
    catch (error) { if (error.message !== 'SECOND_BRAIN_SCOPED_RESPONSE_INVALID') throw error; denied++; }
  }
  if (denied !== 3 || parsed.pages.length === 0) throw new Error('acceptance failed');
  results.push({ method: request.method, pages: parsed.pages.length, substitutions_denied: denied,
    records: parsed.pages.reduce((sum, page) => sum + ('evidence' in page.parsed ? page.parsed.evidence.length : 0), 0) });
}
} finally { await transport.close(); }
process.stdout.write(JSON.stringify(results));
