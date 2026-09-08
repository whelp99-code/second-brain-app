// Synthetic acceptance only. Persistent native transcripts are confined to this fixture.
import assert from 'node:assert/strict';
import {spawnSync,execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdirSync,readFileSync,realpathSync,statSync,writeFileSync,copyFileSync,chmodSync} from 'node:fs';
import {join,dirname,basename} from 'node:path';
import {auditReferenceModelEvents,REFERENCE_ANSWER_FIELDS} from './reference_model_events.mjs';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// Synchronous acceptance-only scope: no concurrent filesystem work during spawnSync.
export function withPrivateUmask(callback) {
  const previous=process.umask(0o077);
  try { const result=callback(); assert(!result || typeof result.then!=='function','Synchronous callback required'); return result; } finally { process.umask(previous); }
}
export function nativeSessionFixture({root,schemaPath,model}) {
  const originalHome=process.env.HOME;
  assert(originalHome && (!process.env.CODEX_HOME || process.env.CODEX_HOME===join(originalHome,'.codex')),
    'Fixture requires the default installed authentication location');
  const nativeHome=join(root,'native-codex'); const client=join(root,'native-client'); const temporary=join(root,'native-tmp');
  for(const path of [nativeHome,client,temporary]) mkdirSync(path,{mode:0o700});
  const originalCodex=join(originalHome,'.codex'); const auth=join(originalCodex,'auth.json');
  assert(statSync(auth).isFile(),'Installed authentication unavailable');
  const launcher=realpathSync(execFileSync('which',['codex'],{encoding:'utf8'}).trim());
  assert(process.platform==='linux' && process.arch==='x64','This native acceptance is Linux x64 only');
  assert(basename(launcher)==='codex.js' && basename(dirname(launcher))==='bin','Unsupported installed launcher layout');
  const packageRoot=dirname(dirname(launcher));
  assert(JSON.parse(readFileSync(join(packageRoot,'package.json'),'utf8')).name==='@openai/codex');
  const vendor=join(packageRoot,'node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin');
  const binaries=[];
  for (const name of ['codex','codex-code-mode-host']) {
    const source=join(vendor,name); const target=join(root,name);
    const sourceInfo=statSync(source);
    assert(sourceInfo.isFile() && sourceInfo.nlink===1 && sourceInfo.uid===process.getuid());
    const digest=createHash('sha256').update(readFileSync(source)).digest('hex');
    copyFileSync(source,target); chmodSync(target,0o500);
    assert.equal(createHash('sha256').update(readFileSync(target)).digest('hex'),digest);
    assert.equal(createHash('sha256').update(readFileSync(source)).digest('hex'),digest);
    assert((statSync(target).mode & 0o022)===0);
    binaries.push({source,target,sha256:digest,source_mode:sourceInfo.mode & 0o777,source_uid:sourceInfo.uid,source_nlink:sourceInfo.nlink});
  }
  const executable=join(root,'codex');
  writeFileSync(join(nativeHome,'auth.json'),'',{mode:0o600});
  const env=Object.fromEntries(['HOME','PATH','LANG','TZ'].filter(key=>process.env[key]).map(key=>[key,process.env[key]]));
  // Keep HOME/CODEX_HOME unchanged. The private mount replaces only Codex state and
  // exposes the installed auth file read-only; no credential bytes are copied.
  const prefix=['--die-with-parent','--ro-bind','/','/','--bind',nativeHome,originalCodex,
    '--ro-bind',auth,auth,'--bind',client,client,'--bind',temporary,'/tmp'];
  const preflight=spawnSync('/usr/bin/bwrap',[...prefix,'/usr/bin/python3','-c',
    'import os,stat; p=os.path.expanduser("~/.codex/auth.json"); s=os.stat(p); '
    +'assert stat.S_ISREG(s.st_mode) and s.st_nlink==1; assert os.access(p,os.R_OK) and not os.access(p,os.W_OK); '
    +'assert os.listdir(os.path.dirname(p))==["auth.json"]; print("auth_mount_read_only")'],{cwd:client,env,encoding:'utf8',timeout:5000});
  assert.equal(preflight.status,0,preflight.stderr); assert.equal(preflight.stdout.trim(),'auth_mount_read_only');
  const options=['--ignore-user-config','--skip-git-repo-check','--json','--model',model,'--output-schema',schemaPath,
    '-c','approval_policy="never"','-c','sandbox_mode="read-only"','-c','web_search="disabled"',
    '-c','features.apps=false','-c','features.shell_tool=false','-c','features.multi_agent=false',
    '-c','features.plugins=false','-c','features.remote_plugin=false','-c','features.hooks=false',
    '-c','features.skill_search=false','-c','features.skill_mcp_dependency_install=false'];
  const ids=new Set(); const calls=[];
  function run(label,head,prompt,expected) {
    assert(/^[a-z0-9-]+$/.test(label));
    const started=performance.now();
    const result=withPrivateUmask(()=>spawnSync('/usr/bin/bwrap',[...prefix,executable,'exec',...head,...options,'-'],{
      cwd:client,env,input:prompt,encoding:'utf8',timeout:60000,maxBuffer:4*1024*1024}));
    writeFileSync(join(root,`${label}.native.jsonl`),result.stdout??'',{mode:0o600});
    writeFileSync(join(root,`${label}.native.stderr`),result.stderr??'',{mode:0o600});
    if(result.error) throw result.error;
    assert.equal(result.status,0,result.stderr);
    const audited=auditReferenceModelEvents(result.stdout,expected);
    assert(uuid.test(audited.thread_id),'Native thread ID is not a UUID');
    calls.push({label,thread_id:audited.thread_id,expected_thread_id:expected??null,elapsed_ms:Math.round(performance.now()-started),
      stdout_digest:`sha256:${createHash('sha256').update(result.stdout).digest('hex')}`});
    return audited;
  }
  return {
    open(label) {
      const result=run(`${label}-bootstrap`,[],
        'Initialize an empty synthetic reference acceptance session. No memory has been provided. Use no tools. '
        +'Return state no_data and all other fields null.');
      assert.deepEqual(result.response,{state:'no_data',...Object.fromEntries(REFERENCE_ANSWER_FIELDS.map(field=>[field,null]))});
      assert(!ids.has(result.thread_id),'Bootstrap unexpectedly reused a session'); ids.add(result.thread_id);
      return Object.freeze({client_id:'codex-exec-native',session_id:result.thread_id,epoch_id:'initial'});
    },
    resume(label,session,prompt) {
      assert(ids.has(session.session_id),'Only a completed bootstrap can be resumed');
      return run(label,['resume',session.session_id],prompt,session.session_id);
    },
    evidence() { return {native_home:nativeHome,client_root:client,credential_copied:false,auth_read_only:true,
      launcher,binaries,write_isolation_only:true,host_files_readable:true,executable,executable_sha256:createHash('sha256').update(readFileSync(executable)).digest('hex'),
      version:execFileSync(executable,['--version'],{encoding:'utf8',env}).trim(),environment_keys:Object.keys(env),calls}; },
  };
}
