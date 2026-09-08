// Isolated JARVIS process/restart and fresh-copy acceptance. No operational state is used.
import assert from 'node:assert/strict';
import {fork} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync,readFileSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const build = resolve(process.argv[2]);
const load = file => import(pathToFileURL(join(build,file)).href);
const {AuthorityDb} = await load('src/db.js');
const {createProductionMemoryReference} = await load('src/memory-reference-production.js');
const {MemoryReferenceProvider,REFERENCE_NOW} = await load('tests/fixtures/memory-reference-provider.js');
const budgets = {max_records:8,max_record_bytes:4096,max_bytes:16384};
if (process.argv[3] === '--child') {
  const input = JSON.parse(readFileSync(process.argv[4],'utf8'));
  const db = new AuthorityDb(input.path);
  const runtime = createProductionMemoryReference(db, {transport:new MemoryReferenceProvider(),
    read_fence_config:input.config,projection_key:Buffer.alloc(32,input.key ?? 7),clock:()=>REFERENCE_NOW});
  let callbacks = 0;
  try {
    const ref = await runtime.reader.read('기억',budgets);
    await runtime.reader.submitInSession(ref,async () => {
      callbacks++;
      if (input.crash) {
        process.send({phase:'callback_entered',callbacks});
        await new Promise(()=>{});
      }
      return 'callback-completed';
    },input.session);
    process.send({phase:'completed',callbacks});
  } catch(error) { process.send({phase:'rejected',code:error.code ?? error.message,callbacks}); }
  finally { db.close(); process.disconnect(); }
} else {
  const root = mkdtempSync(join(tmpdir(),'sb-reference-delivery-'));
  const {memoryDatabase} = await load('tests/fixtures/memory-candidate-store.js');
  const {memoryReadFenceFixture} = await load('tests/fixtures/memory-read-fence.js');
  const {buildFreshAuthority} = await load('src/memory-authority-fresh-builder.js');
  const database = await memoryDatabase();
  const {config} = memoryReadFenceFixture(database);
  const session = {client_id:'process-fixture',session_id:'process-session',epoch_id:'epoch-1'};
  const base = {path:database.path,config,session};
  let count = 0;
  async function invoke(input,kill=false) {
    const path = join(root,`child-${++count}.json`); writeFileSync(path,JSON.stringify(input),{mode:0o600});
    const child = fork(fileURLToPath(import.meta.url),[build,'--child',path],{stdio:['ignore','pipe','pipe','ipc'],env:{...process.env,TMPDIR:root}});
    const exit = once(child,'exit',{signal:AbortSignal.timeout(20000)});
    let stderr=''; child.stderr.on('data',chunk=>{stderr+=chunk;});
    try {
      const [message] = await once(child,'message',{signal:AbortSignal.timeout(15000)});
      if (kill) { assert.equal(message.phase,'callback_entered'); child.kill('SIGKILL'); }
      const [code,signal] = await exit;
      assert.equal(kill ? signal : code,kill ? 'SIGKILL' : 0,stderr);
      return {...message,exit_code:code,signal};
    } finally { if (child.exitCode===null && child.signalCode===null) child.kill('SIGKILL'); }
  }
  try {
    const completed = await invoke(base); assert.equal(completed.phase,'completed');
    const duplicate = await invoke(base); assert.equal(duplicate.code,'MEMORY_REFERENCE_ALREADY_SUBMITTED'); assert.equal(duplicate.callbacks,0);
    const crashed = await invoke({...base,session:{...session,session_id:'crash-session'},crash:true},true);
    const recovered = await invoke({...base,session:{...session,session_id:'crash-session',epoch_id:'epoch-2'}});
    assert.equal(recovered.code,'MEMORY_REFERENCE_DELIVERY_UNCONFIRMED'); assert.equal(recovered.callbacks,0);
    const changedKey = await invoke({...base,key:8}); assert.equal(changedKey.code,'MEMORY_REFERENCE_KEY_CHANGED');
    const tokens = database.authority.db.prepare('SELECT epoch_key,record_set_key,payload_key FROM personal_context_reference_attempts').all()
      .flatMap(row=>Object.values(row)).concat(database.authority.db.prepare('SELECT binding_key FROM personal_context_reference_sessions').all().map(row=>row.binding_key));
    database.authority.db.exec('UPDATE memory_surface_authority SET privacy_epoch=privacy_epoch+1 WHERE singleton_id=1');
    const fresh = join(root,'fresh.sqlite');
    const compacted = await buildFreshAuthority(database.authority,fresh,{sensitive_material:tokens.map(value=>Buffer.from(value))});
    assert.equal(compacted.integrity_check,'ok');
    for (const token of tokens) assert(!readFileSync(fresh).includes(Buffer.from(token)));
    const resumed = await invoke({...base,path:fresh,session:{...session,epoch_id:'epoch-2'}});
    assert.equal(resumed.code,'MEMORY_REFERENCE_SESSION_INVALIDATED'); assert.equal(resumed.callbacks,0);
    const result = {status:'passed',fixture_origin:'synthetic',root,build,database_root:database.root,
      completed,duplicate,crashed,recovered,changed_key:changedKey,restored_session:resumed,
      fresh_identity_tokens_absent:tokens.length,integrity_check:compacted.integrity_check,
      native_session_adapter:false,model_called:false,production_changed:false};
    writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2));
    process.stdout.write(JSON.stringify(result,null,2)+'\n');
  } finally { database.authority.close(); }
}
