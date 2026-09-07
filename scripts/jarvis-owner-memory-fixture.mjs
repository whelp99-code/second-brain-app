// Synthetic owner approval in a fresh JARVIS authority DB; never production authority.
import {join} from 'node:path';

export async function ownerMemoryFixture(load, now) {
  const {memoryDatabase, closeMemoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
  const {inferredMemoryInput, memoryPolicy} = await load('tests/fixtures/memory-candidate-fixture.js');
  const {localKey} = await load('tests/helpers.js');
  const {MemoryCandidateStore, MemoryCandidateDispatchSpool, ControlPlane, signCommandApproval} = await load('src/index.js');
  const {MemoryMutationService} = await load('src/dashboard/memory-mutation-service.js');
  const {MemoryTokenCache} = await load('src/dashboard/memory-token-cache.js');
  const {createDashboardSession} = await load('src/dashboard/session.js');
  const {resolveSpooledDispatch} = await load('src/memory-outbox-dispatch-request.js');
  const database = await memoryDatabase();
  try {
    const review = join(database.root,'candidate-review');
    const dispatchRoot = join(database.root,'candidate-dispatch');
    const input = inferredMemoryInput();
    for (const ref of input.source.references) {
      ref.observed_at = now.toISOString();
      ref.fresh_until = new Date(now.getTime()+3600000).toISOString();
      ref.expires_at = new Date(now.getTime()+86400000).toISOString();
    }
    const store = new MemoryCandidateStore(database.authority,memoryPolicy(),()=>now);
    store.attachReviewSpool(review);
    const candidate = store.classify(input);
    const mutation = new MemoryMutationService({authority:database.authority,clock:()=>now,
      session:createDashboardSession('isolated-owner-acceptance'),
      tokens:new MemoryTokenCache(Buffer.alloc(32,1),()=>now),
      candidate_review_spool_root:review,candidate_dispatch_spool_root:dispatchRoot});
    const command = mutation.stageCandidateDecision({candidate_id:candidate.candidate_id,
      operation:'remember',decision:'confirm',intent_id:`memui:intent:v1:${'1'.repeat(64)}`});
    if (!command) throw new Error('owner confirmation was not staged');
    new ControlPlane(database.authority).decide(signCommandApproval({schema_version:1,
      receipt_id:'isolated-owner-confirmation',request_id:command.request_id,decision:'approve',
      command_digest:command.command_digest,signer_principal_id:'principal:owner',
      authenticated_session_id:'isolated-owner-acceptance',key_id:'decision-test',algorithm:'Ed25519',
      issued_at:now.toISOString(),not_before:now.toISOString(),expires_at:command.expires_at,
      nonce:'isolated-owner-confirmation',max_uses:1,status:'issued'},localKey(database.authority)),now);
    const dispatch = new MemoryCandidateDispatchSpool(dispatchRoot).read(candidate.candidate_id);
    const request = resolveSpooledDispatch({candidate_id:candidate.candidate_id,
      dispatch_spool_digest:dispatch.dispatch_spool_digest,roots:{review,dispatch:dispatchRoot},now});
    return {database,request,dispatch_args:{schema_version:2,dispatch_spool_digest:dispatch.dispatch_spool_digest},
      dispatch_target:{candidate_id:candidate.candidate_id,candidate_digest:candidate.candidate_digest,
        classification_digest:candidate.classification_digest}};
  } catch(error) {
    closeMemoryDatabase(database);
    throw error;
  }
}
