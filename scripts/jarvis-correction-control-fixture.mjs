// Synthetic signed owner confirmation, actual JARVIS lifecycle and compaction.
import assert from 'node:assert/strict';
import {mkdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';

export async function correctionControlFixture({load,jarvis,database,key,config,transport,targets,scope,content,now,root}) {
  const {ControlPlane,MemoryCandidateStore,ApprovedCommandExecutor,signCommandApproval} = await load('src/index.js');
  const {localKey} = await load('tests/helpers.js');
  const {verifiedMemoryInput,MEMORY_NOW} = await load('tests/fixtures/memory-candidate-fixture.js');
  const {insertMemoryVerification,memoryVerificationPayload} = await load('tests/fixtures/memory-candidate-store.js');
  const {AuthorityDatabaseRuntime} = await load('src/authority-database-runtime.js');
  const {MemoryAuthorityCompactor} = await load('src/memory-authority-compactor.js');
  const {MemoryManagedSurfaceScanner} = await load('src/memory-managed-surface-scanner.js');
  const {MemoryLifecycleBarriers,NoopMemoryLifecycleBarrierSink} = await load('src/memory-lifecycle-barriers.js');
  const {ProductionMemoryLifecycleObserver} = await load('src/memory-lifecycle-observer.js');
  const {SecondBrainStatusObservationSource} = await load('src/second-brain-lifecycle-observations.js');
  const {SecondBrainEffectService} = await load('src/second-brain-effect-service.js');
  const {createSecondBrainWriteRequestAdapter} = await load('src/second-brain-write-adapter.js');
  const {ProductionMemoryLifecycleService} = await load('src/memory-lifecycle-service.js');
  const authority = database.authority;
  const control = new ControlPlane(authority);
  const ownerKey = localKey(authority);
  const approve = (input,at) => {
    const staged = control.stage(input,at);
    control.decide(signCommandApproval({schema_version:1,receipt_id:`approval:${input.request_id}`,
      request_id:input.request_id,decision:'approve',command_digest:staged.command_digest,
      signer_principal_id:'principal:owner',authenticated_session_id:'correction-acceptance',key_id:'decision-test',
      algorithm:'Ed25519',issued_at:at.toISOString(),not_before:at.toISOString(),expires_at:input.expires_at,
      nonce:`approval-nonce:${input.request_id}`,max_uses:1,status:'issued'},ownerKey),at);
  };
  const candidateAt = new Date(MEMORY_NOW);
  const candidateInput = verifiedMemoryInput({authority_id:'correction-acceptance',operation:'correct',
    idempotency_key:'candidate:correction-acceptance',statement:'Prior fixture memory requires correction.'});
  insertMemoryVerification(authority,memoryVerificationPayload(candidateInput));
  const candidate = new MemoryCandidateStore(authority,
    JSON.parse(readFileSync(join(jarvis,'config/personal-os-policy.json'),'utf8')),()=>candidateAt).classify(candidateInput);
  assert.equal(candidate.state,'awaiting_confirmation');
  const confirmation = {schema_version:1,request_id:'correction-confirmation',action:'memory.confirm',action_level:3,
    target:{candidate_id:candidate.candidate_id,candidate_digest:candidate.candidate_digest,classification_digest:candidate.classification_digest},
    args:{schema_version:1,operation:'correct',evidence_digest:`sha256:${'b'.repeat(64)}`},reversible:false,
    requested_by:'principal:owner',requested_at:candidateAt.toISOString(),expires_at:new Date(candidateAt.getTime()+300000).toISOString(),
    nonce:'nonce:correction-confirmation'};
  approve(confirmation,candidateAt);
  assert.equal((await new ApprovedCommandExecutor(authority,undefined,undefined,{},()=>candidateAt)
    .execute(confirmation.request_id,'fixture',candidateAt)).state,'completed');
  const layout = Object.fromEntries(['spool','state','dist','backup','restore'].map(name=>[`${name}_root`,join(root,'jarvis',name)]));
  for (const path of Object.values(layout)) mkdirSync(path,{recursive:true,mode:0o700});
  const runtime = new AuthorityDatabaseRuntime(authority,{registry_root:join(root,'jarvis','registry'),watchdog_ms:5000});
  let clock = now; let writes = 0; let compactions = 0; let observations = 0; let failCompletion = false;
  const adapter = createSecondBrainWriteRequestAdapter(transport,authority,()=>clock);
  let request;
  const writer = {write:async value=>{writes++;request=value;return adapter.write(value);}};
  const provider = new SecondBrainEffectService({authority,transport,writer,clock:()=>clock,
    provider_instance_id:config.provider_instance_id,signing_key_id:config.signing_key_id,private_key:key});
  const observer = new ProductionMemoryLifecycleObserver({authority,provider,clock:()=>clock,
    observations:new SecondBrainStatusObservationSource(provider)});
  const compactor = new MemoryAuthorityCompactor({runtime,scanner:new MemoryManagedSurfaceScanner({authority,layout}),layout,clock:()=>clock});
  const barriers = new MemoryLifecycleBarriers(authority,new NoopMemoryLifecycleBarrierSink());
  const service = new ProductionMemoryLifecycleService({authority,spool_root:layout.spool_root,writer,provider,
    signing_key_id:config.signing_key_id,private_key:key,subject_key:Buffer.alloc(32,11),clock:()=>clock,
    observer:{correction:async row=>{observations++;return observer.correction(row);},
      deletion:row=>observer.deletion(row),export:row=>observer.export(row)},
    compactor:{compact:async input=>{compactions++;return compactor.compact(input);},recover:id=>compactor.recover(id)},barriers:{reach:async input=>{
      const event=await barriers.reach(input);
      if (input.barrier_id==='before_settlement_commit' && failCompletion) {
        failCompletion=false;
        authority.db.exec(`CREATE TRIGGER fail_correction_completion BEFORE INSERT ON control_events
          WHEN NEW.event_type='control.command.completed' AND NEW.subject='correction-dispatch'
          BEGIN SELECT RAISE(ABORT,'INJECTED_FINAL_EVENT_FAILURE'); END;`);
      }
      return event;
    }}},
  async()=>runtime.close());
  const action = await service.prepareCorrection({control_request_id:'correction-dispatch',candidate_id:candidate.candidate_id,
    provider_instance_id:config.provider_instance_id,targets,scope,content,requested_at:now,
    expires_at:new Date(now.getTime()+600000),nonce:'nonce:correction-dispatch'});
  approve(action,now);
  const result = await new ApprovedCommandExecutor(authority,undefined,undefined,{},()=>clock,undefined,provider,service)
    .execute(action.request_id,'fixture',now);
  assert.equal(result.state,'uncertain',JSON.stringify(result));
  assert(request);
  return {request,service,action,
    failNextCompletion:()=>{failCompletion=true;},
    advance:()=>{clock=new Date(now.getTime()+1200000);},
    counts:()=>({writes,compactions,observations}),
    controlState:()=>authority.db.prepare('SELECT state FROM control_command_requests WHERE request_id=?').get(action.request_id).state};
}
