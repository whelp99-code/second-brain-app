'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const core=require('../sync-core.cjs');

async function snapshot(count=7) {
  const files=[];
  for(let i=0;i<count;i++) {
    const content='# 기록 '+i+'\n';
    files.push({path:`Auto/Events/event-${i}.md`,content,sha256:await core.digest(content)});
  }
  const generation=await core.digest(core.canonical(files));
  return {schema_version:1,generation,cursor:generation,managed_prefix:'Auto/',complete:true,
          day:'2026-09-26',timezone:'Asia/Seoul',files};
}
function pages(snapshot, size=2) {
  return async route=> {
    const query=new URL('https://fixture.invalid/'+route).searchParams;
    const start=Number(query.get('cursor')||0),end=Math.min(start+size,snapshot.files.length);
    return {...snapshot,files:snapshot.files.slice(start,end),page_offset:start,total_files:snapshot.files.length,
            snapshot_complete:true,complete:start===0&&end===snapshot.files.length,
            page_complete:end===snapshot.files.length,next_cursor:end===snapshot.files.length?null:String(end)};
  };
}

test('all pages verified against full generation before applying',async()=>{
  const manifest=await snapshot();
  const result=await core.collectManifest(pages(manifest),{day:manifest.day});
  assert.deepEqual(result.files,manifest.files);
  assert.equal(result.complete,true);
});
test('changed generation midway aborts instead of combining old and new files',async()=>{
  const manifest=await snapshot(),fetch=pages(manifest);let count=0;
  await assert.rejects(core.collectManifest(async route=>{
    const page=await fetch(route);if(count++) page.generation='a'.repeat(64);return page;
  }),/INVALID_MANIFEST_PAGE|VIEW_GENERATION_CHANGED/);
});
test('truncated or replayed page cannot advance complete cursor',async()=>{
  const manifest=await snapshot(),fetch=pages(manifest);
  await assert.rejects(core.collectManifest(async route=>{
    const value=await fetch(route);value.next_cursor=null;return value;
  }),/INCOMPLETE_MANIFEST/);
  await assert.rejects(core.collectManifest(async()=>fetch('manifest')),/INVALID_MANIFEST_PAGE/);
});
test('pagination validates every hash and never accepts partial snapshot as complete',async()=>{
  const manifest=await snapshot(),fetch=pages(manifest);
  await assert.rejects(core.collectManifest(async route=>{
    const value=await fetch(route);value.files[0]={...value.files[0],content:'changed'};return value;
  }),/VIEW_HASH_MISMATCH/);
  const fresh=await snapshot();
  const result=await core.collectManifest(async route=>({...await pages(fresh)(route),snapshot_complete:false}));
  assert.equal(result.complete,false);
});
for(const p of ['Auto/History.md','Auto/Questions.md','Auto/Relations.md','Auto/Predictions.md',
                'Auto/Predictions/a'.replace(/a$/,'a'.repeat(64))+'.md']) {
  test('new managed view path '+p,()=>assert.equal(core.validatePath(p),p));
}

function pluginRuntime(desktop=false) {
  class Modal { constructor(app){this.app=app;} open(){} }
  class Plugin {
    constructor(){this.commands=[];this.protocols={};this.app={workspace:{on:()=>({}),getActiveFile:()=>null},vault:{}};}
    async loadData(){return null;}
    async saveData(value){this.saved=value;}
    addStatusBarItem(){return {setText(){}};}
    addSettingTab(){}
    addCommand(value){this.commands.push(value);}
    registerObsidianProtocolHandler(name,handler){this.protocols[name]=handler;}
    registerDomEvent(){}
    registerEvent(){}
  }
  const obsidian={Plugin,Modal,PluginSettingTab:class{},Setting:class{},Notice:class{},
                  TFile:class{},TFolder:class{},Platform:{isDesktopApp:desktop},requestUrl:async()=>({status:200,json:{}})};
  const code='const syncCore = injectedCore;\n'+fs.readFileSync(path.join(__dirname,'..','main.src.cjs'),'utf8');
  const context={module:{exports:{}},require:name=>{assert.equal(name,'obsidian');return obsidian;},
                 injectedCore:core,TextEncoder,URL,URLSearchParams,Intl,Date,Number,JSON,Map,Set,
                 globalThis:globalThis,document:{visibilityState:'visible'},window:{},setTimeout};
  vm.runInNewContext(code,context,{filename:'main.src.cjs'});
  return {Plugin:context.module.exports,obsidian};
}
test('shipping plugin registers workflow commands and question protocol on mobile',async()=>{
  const runtime=pluginRuntime(false),plugin=new runtime.Plugin();await plugin.onload();
  for(const name of ['sync-memory-view','select-memory-day','recall-memory','memory-questions',
                    'memory-relations','memory-predictions','memory-health','save-selected-personal-note'])
    assert.ok(plugin.commands.some(c=>c.id===name),name);
  assert.equal(typeof plugin.protocols['sb-life-question'],'function');
  assert.equal(plugin.token,'');
});
test('plugin does not persist login tokens',async()=>{
  const runtime=pluginRuntime(),plugin=new runtime.Plugin();await plugin.onload();
  plugin.token='private-session-token';await plugin.persist();
  assert.ok(!JSON.stringify(plugin.saved).includes('private-session-token'));
});
