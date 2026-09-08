import {createHash} from "node:crypto";
// Isolated compiled backend acceptance; synthetic authority and provider only.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const [build,mode,root]=process.argv.slice(2);assert(build?.startsWith('/'));
process.umask(0o077);process.chdir(build);
const load=path=>import(pathToFileURL(join(build,'dist',path)));
const {MemoryProjectionAuthority}=await load('src/memory-projection-authority.js');
const {MemoryCandidateStore}=await load('src/memory-candidate-store.js');
const {memoryPolicy,inferredMemoryInput,MEMORY_NOW}=await load('tests/fixtures/memory-candidate-fixture.js');
const {createSecondBrainWriteRequestAdapter}=await load('src/second-brain-write-adapter.js');
const {AuthorityDb}=await load('src/db.js');
const {outboxFixture,claimAction}=await load('tests/fixtures/memory-outbox-fixture.js');
const deny=(db,id,now)=>new MemoryProjectionAuthority(db).quarantineUnresolved({kind:'dashboard_projection',id,component_id:id},now);
const code=expected=>error=>error.code===expected;
let result;
if(mode==='seed') {
  const f=await outboxFixture();
  try {
    const {canonicalize}=await load('src/canonical.js');
    const {request_id,request_digest,...base}=f.request;
    const digest='sha256:'+createHash('sha256').update('orca-jarvis/memory-write-request/v1\0').update(canonicalize(base)).digest('hex');
    const providerRequest={...base,request_id:'memreq:pos:v1:'+digest.slice(7),request_digest:digest};
    const {parseSecondBrainWriteRequest}=await load('src/second-brain-write-request.js');
    assert(parseSecondBrainWriteRequest(providerRequest,f.clock.now));
    let calls=0;
    const transport={call:async(method,args)=>{assert.equal(method,'sb_write_request');calls++;
      return {kind:'data',value:{schema_version:1,...await f.writer.write(args.request)}};},restart:async()=>{},close:async()=>{},diagnostics:()=>[]};
    const writer=createSecondBrainWriteRequestAdapter(transport,f.database.authority,()=>f.clock.now);
    assert.equal((await writer.write(providerRequest)).kind,'accepted');assert.equal(calls,1);
    const saga=f.service.enqueue(claimAction(f));
    const input=inferredMemoryInput({idempotency_key:'candidate:acceptance:quarantine'});
    const candidate=new MemoryCandidateStore(f.database.authority,memoryPolicy(),()=>new Date(MEMORY_NOW)).classify(input);
    deny(f.database.authority,f.request.candidate_id,f.clock.now);deny(f.database.authority,candidate.candidate_id,f.clock.now);
    assert.equal((await writer.write(providerRequest)).code,'SECOND_BRAIN_WRITE_AUTHORITY_INVALID');assert.equal(calls,1);
    writeFileSync(join(root,'state.json'),JSON.stringify({database:f.database,request:providerRequest,input,
      candidate_id:candidate.candidate_id,outbox_id:saga.outbox_id,now:f.clock.now.toISOString()},(key,value)=>key==='authority'?undefined:value));
    result={mode,pid:process.pid,normal_provider_fixture_calls:1,post_quarantine_provider_calls:0,queued_before_quarantine:true};
  } finally {f.database.authority.close();}
} else if(mode==='restart') {
  const state=JSON.parse(readFileSync(join(root,'state.json'),'utf8'));const db=new AuthorityDb(state.database.path);
  try {
    const now=new Date(state.now);let calls=0;
    const transport={call:async()=>{calls++;return {kind:'no_data',reason:'empty_result'};},restart:async()=>{},close:async()=>{},diagnostics:()=>[]};
    const writer=createSecondBrainWriteRequestAdapter(transport,db,()=>now);
    assert.equal((await writer.write(state.request)).code,'SECOND_BRAIN_WRITE_AUTHORITY_INVALID');
    assert.throws(()=>new MemoryCandidateStore(db,memoryPolicy(),()=>new Date(MEMORY_NOW)).classify(state.input),code('MEMORY_CANDIDATE_SUPPRESSED'));
    const {MemoryOutboxService}=await load('src/memory-outbox.js');
    const noData=async()=>({kind:'no_data',checked_at:state.now,fresh_until:state.now});
    const service=new MemoryOutboxService({authority:db,writer,reader:{search:noData,readPage:noData,recentChanges:noData,openConflicts:noData},
      clock:()=>now,candidate_review_spool_root:join(state.database.root,'candidate-review'),
      candidate_dispatch_spool_root:join(state.database.root,'candidate-dispatch')});
    await service.runOnce('restart-worker');assert.equal(calls,0);
    assert.equal(service.get(state.outbox_id).state,'failed');
    assert.deepEqual(db.db.prepare('SELECT COUNT(*) AS count FROM memory_outbox_attempts').get(),{count:0});
    result={mode,pid:process.pid,replay_rejected:true,provider_calls:0,outbox_state:'failed',dispatch_attempts:0};
  } finally {db.close();}
} else if(mode==='http') {
  const {memoryDatabase}=await load('tests/fixtures/memory-candidate-store.js');const f=await memoryDatabase();let server;
  try {
    const now=new Date(MEMORY_NOW);const reviewRoot=join(f.root,'review');const dispatchRoot=join(f.root,'dispatch');
    const store=new MemoryCandidateStore(f.authority,memoryPolicy(),()=>now);store.attachReviewSpool(reviewRoot);
    const input=inferredMemoryInput();const c=store.classify(input);
    const {createDashboardServer}=await load('src/dashboard/server.js');
    const {Task32ReadAdapter}=await load('tests/fixtures/task32-memory-test-support.js');
    server=createDashboardServer({db:f.authority,staticRoot:f.root,host:'127.0.0.1',port:0,clock:()=>now,
      memoryAdapter:new Task32ReadAdapter(),memoryCandidateReviewSpoolRoot:reviewRoot,memoryCandidateDispatchSpoolRoot:dispatchRoot});
    const origin=`http://127.0.0.1:${server.address.port}`;const session=await(await fetch(origin+'/api/v1/session')).json();
    const path=origin+'/api/v1/memory/candidates/'+encodeURIComponent(c.candidate_id);
    const headers={'x-jarvis-csrf':session.csrf_token,origin,'content-type':'application/json'};
    const review=await fetch(path,{headers});assert.equal(review.status,200);const body=await review.json();assert.equal(body.statement,input.statement);
    const stage=await fetch(path+'/actions/stage-decision',{method:'POST',headers,body:JSON.stringify({schema_version:2,
      intent_id:`memui:intent:v1:${'d'.repeat(64)}`,operation:'remember',decision:'confirm',review_digest:body.review_digest})});
    assert.equal(stage.status,202);const commandId=(await stage.json()).request_id;
    deny(f.authority,c.candidate_id,now);
    const hidden=await fetch(path,{headers});assert.equal(hidden.status,404);assert(!(await hidden.text()).includes(input.statement));
    const {ControlPlane,signCommandApproval}=await load('src/control-plane.js');const {localKey}=await load('tests/helpers.js');
    const control=new ControlPlane(f.authority);const command=control.get(commandId);
    const receipt=signCommandApproval({schema_version:1,receipt_id:'actual-suppression-owner',request_id:commandId,
      decision:'approve',command_digest:command.command_digest,signer_principal_id:'principal:owner',authenticated_session_id:'owner-session',
      key_id:'decision-test',algorithm:'Ed25519',issued_at:now.toISOString(),not_before:now.toISOString(),expires_at:command.expires_at,
      nonce:'actual-suppression-owner',max_uses:1,status:'issued'},localKey(f.authority));
    assert.throws(()=>control.decide(receipt,now),code('MEMORY_CANDIDATE_SUPPRESSED'));
    assert.deepEqual(f.authority.db.prepare('SELECT COUNT(*) AS count FROM memory_candidate_owner_decisions').get(),{count:0});
    assert.deepEqual(f.authority.db.prepare('SELECT COUNT(*) AS count FROM memory_candidate_dispatch_publications').get(),{count:0});
    result={mode,pid:process.pid,review_before:200,stage_before:202,review_after:404,hidden_body_absent:true,
      prepared_approval_rejected:true,owner_decisions:0,dispatch_publications:0};
  } finally {if(server){server.close();await server.drain();}f.authority.close();}
} else {
  const fixture=mkdtempSync('/var/tmp/jarvis-candidate-suppression-');const cases=[];
  for(const worker of ['seed','restart','http']) {
    const run=spawnSync(process.execPath,[fileURLToPath(import.meta.url),build,worker,fixture],
      {encoding:'utf8',timeout:30_000,maxBuffer:1024*1024,env:{...process.env,TMPDIR:'/var/tmp'}});
    assert.equal(run.status,0,run.stderr);cases.push(JSON.parse(run.stdout));
  }
  result={status:'passed',root:fixture,build,cases,provider:'deterministic transport fixture',operational_data_used:false,
    native_model_calls:0,source_task_lineage_implemented:false,automatic_capture_enabled:false};
  writeFileSync(join(fixture,'result.json'),JSON.stringify(result,null,2)+'\n');
}
console.log(JSON.stringify(result,null,2));
