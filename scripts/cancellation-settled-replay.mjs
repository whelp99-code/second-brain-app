import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(0, 'utf8'));
const moduleAt = name => import(pathToFileURL(`${input.build}/${name}.js`));
const { AuthorityDb } = await moduleAt('src/db');
const { MemoryCorrectionSaga } = await moduleAt('src/memory-correction-saga');
const { notProvedMemoryObserver, unreachableMemoryCompactor } = await moduleAt('tests/fixtures/memory-lifecycle-runtime');
const db = new AuthorityDb(input.database);
try {
  const saga = new MemoryCorrectionSaga({ authority:db, spool_root:input.spool_root, subject_key:Buffer.alloc(32,3),
    clock:() => new Date(), observer:notProvedMemoryObserver, compactor:unreachableMemoryCompactor,
    writer:{ write:() => { throw new Error('REPLAY_MUST_NOT_WRITE'); } },
    provider:{ requestStatus:() => { throw new Error('REPLAY_MUST_NOT_FETCH'); } } });
  const record = await saga.reconcile(input.correction_id);
  const command = db.db.prepare('SELECT state FROM control_command_requests WHERE request_id=?').get(record.control_request_id);
  const catalog = db.db.prepare('SELECT expected_surface_count,observed_surface_count,omission_count,error_count,match_count FROM memory_surface_catalog_manifests WHERE tombstone_sequence=2').get();
  process.stdout.write(JSON.stringify({ pid:process.pid, record, command, catalog }));
} finally { db.close(); }
