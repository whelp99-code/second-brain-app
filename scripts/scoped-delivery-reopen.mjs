// Isolated acceptance child only. The parent supplies a fixture identity snapshot;
// this is not an HTTP authentication or native-client session transfer mechanism.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const moduleAt = name => import(pathToFileURL(join(process.argv[2], name)).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const { AuthorityDb } = await moduleAt('src/db.js');
const { createProductionScopedMemory } = await moduleAt('src/memory-scoped-production.js');
const authority = new AuthorityDb(input.database);
let memory;
try {
  memory = createProductionScopedMemory(authority, {
    ...input.options,
    authenticated_session: () => input.fixture_session,
    clock: () => new Date(input.now),
  });
  const reference = await memory.reader.read('Cited', input.budgets);
  if (reference.payload.records.length === 0) throw new Error('reopened reader returned no records');
  let callbacks = 0;
  let denied = false;
  try {
    await memory.reader.submitInSession(reference, async () => { callbacks++; }, input.native_session);
  } catch (error) {
    if (error.code !== 'MEMORY_REFERENCE_ALREADY_SUBMITTED') throw error;
    denied = true;
  }
  if (!denied || callbacks !== 0) throw new Error('independent process accepted duplicate delivery');
  process.stdout.write(JSON.stringify({ independent_process: true, duplicate_denied: denied,
    callbacks, records: reference.payload.records.length, fixture_identity_snapshot: true }));
} finally {
  try { await memory?.close(); } finally { authority.close(); }
}
