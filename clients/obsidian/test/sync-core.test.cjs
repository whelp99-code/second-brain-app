'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {digest,canonical,emptyState,applyManifest,WITHDRAWN}=require('../sync-core.cjs');
async function manifest(entries, complete=true) {
  const files=await Promise.all(entries.map(async ([path,content])=>({path,content,sha256:await digest(content)})));
  files.sort((a,b)=>a.path.localeCompare(b.path));
  const generation=await digest(canonical(files));
  return {schema_version:1,complete,files,generation,cursor:generation,managed_prefix:'Auto/'};
}
function memoryHost(initial={}) {
  const files=new Map(Object.entries(initial));
  return {files,saved:emptyState(),writes:0,
    async read(path){return files.has(path)?files.get(path):null;},
    async compareAndWrite(path, expected, content) {
      assert.equal(files.has(path)?files.get(path):null, expected,'CAS mismatch');
      files.set(path,content);this.writes++;
    },
    async save(state){this.saved=structuredClone(state);}
  };
}
test('verified manifest creates only Auto, preserves personal notes',async()=>{
  const host=memoryHost({'MyNotes/2026-09-26.md':'my private words'});
  const view=await manifest([['Auto/Daily/2026-09-26.md','today']]);
  const state=await applyManifest(host,view);
  assert.equal(state.status,'complete');assert.equal(state.cursor,view.cursor);
  assert.equal(host.files.get('MyNotes/2026-09-26.md'),'my private words');
  assert.equal(host.files.get('Auto/Daily/2026-09-26.md'),'today');
});
test('repeated complete snapshot is idempotent',async()=>{
  const host=memoryHost(),view=await manifest([['Auto/Home.md','home']]);
  await applyManifest(host,view);const count=host.writes;
  await applyManifest(host,view,host.saved);assert.equal(host.writes,count);
});
test('unowned file is never adopted even with matching server bytes',async()=>{
  const host=memoryHost({'Auto/Home.md':'same'}),view=await manifest([['Auto/Home.md','same']]);
  const result=await applyManifest(host,view);
  assert.equal(result.status,'conflict');assert.equal(host.writes,0);assert.equal(result.cursor,null);
});
test('user edited owned Auto content is preserved on update',async()=>{
  const host=memoryHost();await applyManifest(host,await manifest([['Auto/Home.md','v1']]));
  const oldCursor=host.saved.cursor;host.files.set('Auto/Home.md','user words');
  const result=await applyManifest(host,await manifest([['Auto/Home.md','v2']]),host.saved);
  assert.equal(host.files.get('Auto/Home.md'),'user words');assert.equal(result.status,'conflict');
  assert.equal(result.cursor,oldCursor);
});
test('withdrawal clears old managed text but not personal notes',async()=>{
  const host=memoryHost({'MyNotes/my.md':'private'});
  await applyManifest(host,await manifest([['Auto/Events/old.md','withdraw me']]));
  await applyManifest(host,await manifest([]),host.saved);
  assert.equal(host.files.get('Auto/Events/old.md'),WITHDRAWN);
  assert.equal(host.files.get('MyNotes/my.md'),'private');
});
test('withdrawal cannot overwrite a user edit',async()=>{
  const host=memoryHost();await applyManifest(host,await manifest([['Auto/Events/old.md','original']]));
  host.files.set('Auto/Events/old.md','my edit');
  const result=await applyManifest(host,await manifest([]),host.saved);
  assert.equal(result.status,'conflict');assert.equal(host.files.get('Auto/Events/old.md'),'my edit');
});
test('partial snapshot cannot prune omitted records or advance cursor',async()=>{
  const host=memoryHost();await applyManifest(host,await manifest([['Auto/Home.md','v1']]));
  const cursor=host.saved.cursor;
  const result=await applyManifest(host,await manifest([],false),host.saved);
  assert.equal(result.status,'partial');assert.equal(result.cursor,cursor);
  assert.equal(host.files.get('Auto/Home.md'),'v1');
});
for(const path of ['../outside.md','MyNotes/private.md','Auto/../secret.md','Auto/Events/../../x.md',
                   'Auto/Events/%2e%2e.md','/Auto/Home.md','Auto\\Home.md','Auto/Events/a.md/evil']) {
  test('reject path '+path+' before any mutation',async()=>{
    const host=memoryHost();await assert.rejects(applyManifest(host,await manifest([[path,'bad']])),/UNSAFE/);
    assert.equal(host.writes,0);
  });
}
for(const content of ['<script>alert(1)</script>','![tracking](https://tracking.invalid/x)',
                      '<iframe src=x>','[run](javascript:evil())','<img src=https://tracking.invalid/>']) {
  test('reject active untrusted content '+content,async()=>{
    const host=memoryHost();await assert.rejects(applyManifest(host,await manifest([['Auto/Home.md',content]])),/UNSAFE/);
    assert.equal(host.writes,0);
  });
}
test('corrupt content hash is rejected before touching existing files',async()=>{
  const host=memoryHost(),view=await manifest([['Auto/Home.md','home']]);
  view.files[0].content='tampered';
  await assert.rejects(applyManifest(host,view),/HASH/);assert.equal(host.writes,0);
});
test('forged generation and duplicate path are rejected',async()=>{
  const host=memoryHost(),view=await manifest([['Auto/Home.md','home']]);
  view.generation='a'.repeat(64);view.cursor=view.generation;
  await assert.rejects(applyManifest(host,view),/GENERATION/);
  await assert.rejects(applyManifest(host,await manifest([['Auto/Home.md','a'],['Auto/Home.md','b']])),/INVALID/);
});
test('disconnect applying 100 records resumes from durable ownership',async()=>{
  const host=memoryHost(),view=await manifest(Array.from({length:100},(_,i)=>['Auto/Events/id-'+i+'.md','content'+i]));
  const read=host.read.bind(host);let reads=0;
  host.read=async path=>{if(++reads===25)throw new Error('synthetic disconnect');return read(path);};
  await assert.rejects(applyManifest(host,view),/disconnect/);
  assert.equal(host.saved.cursor,null);assert.equal(host.saved.status,'applying');
  host.read=read;
  const result=await applyManifest(host,view,host.saved);
  assert.equal(result.status,'complete');assert.equal(host.files.size,100);
});
test('write succeeds but final ownership save fails: journal allows safe recovery',async()=>{
  const host=memoryHost(),view=await manifest([['Auto/Home.md','home']]);
  const save=host.save.bind(host);let saves=0;
  host.save=async state=>{if(++saves===3)throw new Error('disk unavailable');await save(state);};
  await assert.rejects(applyManifest(host,view),/unavailable/);
  assert.equal(host.files.get('Auto/Home.md'),'home');assert.ok(host.saved.intents['Auto/Home.md']);
  host.save=save;
  const result=await applyManifest(host,view,host.saved);
  assert.equal(result.status,'complete');assert.equal(host.writes,1);
});
test('concurrent user edit triggers compare-and-write failure, not overwrite',async()=>{
  const host=memoryHost();await applyManifest(host,await manifest([['Auto/Home.md','v1']]));
  const write=host.compareAndWrite.bind(host);
  host.compareAndWrite=async(...args)=>{host.files.set(args[0],'user racing edit');return write(...args);};
  await assert.rejects(applyManifest(host,await manifest([['Auto/Home.md','v2']]),host.saved),/CAS/);
  assert.equal(host.files.get('Auto/Home.md'),'user racing edit');
});
