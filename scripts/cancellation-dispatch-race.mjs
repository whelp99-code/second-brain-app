import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const input = JSON.parse(readFileSync(0,'utf8'));
const moduleAt = name => import(pathToFileURL(`${input.build}/${name}.js`));
const { correctionPreparedFixture } = await moduleAt('tests/fixtures/memory-correction-control');
const { MemoryCorrectionSaga } = await moduleAt('src/memory-correction-saga');
const { MemoryCorrectionStore } = await moduleAt('src/memory-correction-store');
const { MemoryProjectionAuthority } = await moduleAt('src/memory-projection-authority');
const { MemoryCorrectionCancellationIssuer } = await moduleAt('src/memory-correction-cancellation-issuer');
const { submitDatabaseCorrectionCancellation } = await moduleAt('src/memory-correction-cancellation-submit');
const { createSecondBrainTransport } = await moduleAt('src/second-brain-transport');
const { createSecondBrainWriteRequestAdapter } = await moduleAt('src/second-brain-write-adapter');
const { SecondBrainEffectService } = await moduleAt('src/second-brain-effect-service');
const { cancellationDatabaseFixture } = await moduleAt('tests/fixtures/memory-cancellation-db');
const f = input.race_first==='cancellation' ? await cancellationDatabaseFixture('suppressed', input.resolved)
  : await correctionPreparedFixture(input.resolved);
const mcpPids=[]; const methods={};
const transport = createSecondBrainTransport({launcherPath:input.launcher,configPath:input.config,
  contractPath:input.contract,contractProfile:'cancellation-submit-schema7',
  execFile:(file,args,options) => {const child=execFile(file,args,options);mcpPids.push(child.pid);return child;}});
const call=transport.call.bind(transport);
transport.call=(method,...args) => {methods[method]=(methods[method]??0)+1;return call(method,...args);};
const clock = () => new Date('2026-08-28T12:00:02.000Z');
const issuer = new MemoryCorrectionCancellationIssuer(f.db,clock);
const store = new MemoryCorrectionStore(f.db);
const quarantine = () => new MemoryProjectionAuthority(f.db).quarantineUnresolved({kind:'dashboard_projection',
  id:f.candidate.candidate_id,component_id:f.candidate.candidate_id}, clock());
let calls=0; let cancellation; let denial; let lostResponse=false;
const adapter = createSecondBrainWriteRequestAdapter(transport,f.db,clock);
const writer = {write:async request => {
  calls++;
  const accepted = await adapter.write(request);
  assert.equal(accepted.kind,'accepted',JSON.stringify(accepted));
  // Provider has accepted; the saga has not yet persisted the response.
  quarantine();
  const record = store.getByControl(f.claim.request_id);
  try { await submitDatabaseCorrectionCancellation(issuer,record.correction_id,f.runtime.signing_key_id,
    f.runtime.private_key,transport,clock); assert.fail('cancellation must not be sent'); }
  catch(error) { assert.equal(error.message,'MEMORY_CANCELLATION_UNSENT_UNPROVED'); denial=error.message; }
  return accepted;
}};
const provider = new SecondBrainEffectService({authority:f.db,transport,writer,clock,
  provider_instance_id:'provider:fixture',signing_key_id:f.runtime.signing_key_id,private_key:f.runtime.private_key});
const barriers = f.runtime.barriers;
try {
  const saga = new MemoryCorrectionSaga({...f.runtime,clock,writer,provider,barriers});
  if(input.race_first==='cancellation') {
    const record=store.getByControl(f.claim.request_id);
    const submit=() => submitDatabaseCorrectionCancellation(issuer,record.correction_id,
      f.runtime.signing_key_id,f.runtime.private_key,transport,clock);
    const pending=submit().then(() => {throw new Error('expected response loss');}, error => error);
    await assert.rejects(saga.dispatch(f.claim), /MEMORY_CANDIDATE_SUPPRESSED|MEMORY_CORRECTION_CANCELLED|MEMORY_REQUEST_CANCELLED/);
    assert.equal(calls,0);
    const error=await pending;
    assert.equal(error.disposition,'uncertain',error.stack);
    lostResponse=true;
    await transport.restart();
    cancellation=await submit();
    assert.equal(cancellation.state,'suppression_pending');
  } else {
    const result = await saga.dispatch(f.claim);
    assert.equal(result.state,'reconciling');
    assert.equal(calls,1);
    assert.equal(denial,'MEMORY_CANCELLATION_UNSENT_UNPROVED');
  }
  assert.equal(methods.sb_write_request??0,input.race_first==='request'?1:0);
  assert.equal(methods.sb_submit_cancellation??0,input.race_first==='cancellation'?2:0);
  const record=store.getByControl(f.claim.request_id);
  const cursor=f.db.db.prepare('SELECT active_lane_id,accepted_through_sequence FROM memory_effect_dispatch_cursor').get();
  assert.equal(cursor.accepted_through_sequence,input.race_first==='request'?1:0);
  const intents=f.db.db.prepare('SELECT count(*) AS n FROM memory_correction_cancellation_intents').get().n;
  assert.equal(intents,input.race_first==='cancellation'?1:0);
  process.stdout.write(JSON.stringify({node_pid:process.pid,mcp_pids:mcpPids,transport_methods:methods,race_first:input.race_first,request_id:record.request_id,
    intent_id:cancellation?.intent_id,original_write_calls:calls,cancellation_intents:intents,
    cancellation_denial:denial,response_loss_recovered:lostResponse,jarvis_state:record.state,cursor}));
} finally {await transport.close();await f.close();}
