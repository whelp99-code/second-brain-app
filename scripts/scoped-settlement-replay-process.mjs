import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const load = name => import(pathToFileURL(join(process.argv[2], name)).href);
const { AuthorityDb } = await load('src/db.js');
const { readMemoryScopedSettlement, settleMemoryScopedCompletion } = await load('src/memory-scoped-settlement.js');
const authority = new AuthorityDb(input.database);
try {
  const options = { authority, spoolRoot: input.spoolRoot, providerInstanceId: 'provider:fixture' };
  const at = new Date('2026-08-31T03:31:00.000Z');
  const result = readMemoryScopedSettlement(options, input.lease.outbox_id, at);
  assert.equal(result.kind, 'memory_scoped_settled');
  const before = authority.db.prepare('SELECT count(*) AS n FROM control_command_effects').get().n;
  const client = { withRememberedCompletion: () => { throw new Error('replay must not call provider'); } };
  assert.deepEqual(await settleMemoryScopedCompletion(options, input.lease, client, () => at, input.roots), result);
  assert.equal(authority.db.prepare('SELECT count(*) AS n FROM control_command_effects').get().n, before);
  console.log(JSON.stringify({ atomic_settlement: result, commit_exit: 73, independent_replay: true, provider_calls_on_replay: 0 }));
} finally { authority.close(); }
