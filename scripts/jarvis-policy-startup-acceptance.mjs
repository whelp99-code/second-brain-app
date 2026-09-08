// Synthetic startup/HTTP acceptance against an isolated canonical backend build.
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createInterface} from 'node:readline';
import {fileURLToPath, pathToFileURL} from 'node:url';
const [build, mode, fixture] = process.argv.slice(2);
assert(build?.startsWith('/'), 'absolute isolated build root required');
process.umask(0o077);
const load = path => import(pathToFileURL(join(build, path)));
const {AuthorityDb} = await load('dist/src/db.js');

if (mode) {
  const db = new AuthorityDb(join(fixture, `${mode}.sqlite`));
  await db.migrate();
  try {
    const {createDashboardServer} = await load('dist/src/dashboard/server.js');
    const policyPath = join(fixture, `${mode}-policy.json`);
    const options = {db, staticRoot: fixture, host: '127.0.0.1', port: 0};
    if (mode === 'missing' || mode === 'invalid') {
      if (mode === 'invalid') writeFileSync(policyPath, '{bad policy');
      assert.throws(() => createDashboardServer({...options, remoteApprovalPolicyPath: policyPath}),
        error => error.code === 'REMOTE_APPROVAL_POLICY_UNAVAILABLE');
      process.stdout.write(JSON.stringify({mode, pid: process.pid, rejected_before_listen: true}));
    } else {
      if (mode === 'pinned') {
        copyFileSync(join(build, 'dist/src/personal-os-policy.json'), policyPath);
        options.remoteApprovalPolicyPath = policyPath;
      }
      const server = createDashboardServer(options);
      try {
        if (mode === 'pinned') writeFileSync(policyPath, 'invalid after startup');
        const origin = `http://127.0.0.1:${server.address.port}`;
        const health = await fetch(origin+'/api/v1/health'); assert.equal(health.status,200); await health.text();
        const session = await (await fetch(origin+'/api/v1/session')).json();
        const memory = await fetch(origin+'/api/v1/memory/status', {headers: {'x-jarvis-csrf':session.csrf_token}});
        assert.equal(memory.status,200); await memory.text();
        process.stdout.write(JSON.stringify({mode,pid:process.pid,health:200,memory_status:200,
          policy_reread_after_start:false,cwd:process.cwd()}));
      } finally {server.close(); await server.drain();}
    }
  } finally {db.close();}
} else {
  const root=mkdtempSync('/var/tmp/jarvis-policy-acceptance-');
  const cwd=join(root,'unrelated-cwd');mkdirSync(cwd);
  writeFileSync(join(root,'index.html'),'<!doctype html><title>Synthetic dashboard</title>');
  // A hostile/unrelated cwd config must never override the packaged policy.
  mkdirSync(join(cwd,'config'));writeFileSync(join(cwd,'config/personal-os-policy.json'),'{bad cwd policy');
  const cases=[];
  for(const name of ['default','pinned','missing','invalid']) {
    const result=spawnSync(process.execPath,[fileURLToPath(import.meta.url),build,name,root],
      {cwd,encoding:'utf8',timeout:30_000,maxBuffer:1024*1024});
    assert.equal(result.status,0,result.stderr);cases.push(JSON.parse(result.stdout));
  }
  const db=new AuthorityDb(join(root,'cli.sqlite'));await db.migrate();db.close();
  const args=[join(build,'dist/src/dashboard/main.js'),'--host','127.0.0.1','--port','0',
    '--db',join(root,'cli.sqlite'),'--static-root',root];
  const child=spawn(process.execPath,args,{cwd,stdio:['ignore','pipe','pipe']});
  const lines=createInterface({input:child.stdout});let stderr='';child.stderr.on('data',chunk=>{stderr+=chunk});
  const terminal=once(child,'close');
  try {
    const [origin]=await Promise.race([once(lines,'line',{signal:AbortSignal.timeout(15_000)}),
      terminal.then(([code])=>{throw new Error(`CLI exited before readiness: ${code} ${stderr}`)})]);
    const response=await fetch(origin+'/api/v1/health');assert.equal(response.status,200);await response.text();
    child.kill('SIGTERM');const [code]=await terminal;assert.equal(code,0,stderr);
    cases.push({mode:'cli-default',pid:child.pid,health:200,exit_code:code,cwd});
  } finally {lines.close();if(child.exitCode===null && child.signalCode===null){child.kill('SIGKILL');await terminal;}}
  const failed=spawnSync(process.execPath,[...args,'--policy',join(root,'nonexistent.json')],
    {cwd,encoding:'utf8',timeout:15_000,maxBuffer:1024*1024});
  assert.equal(failed.status,2);assert.equal(failed.stdout,'');assert.equal(failed.stderr.trim(),'REMOTE_APPROVAL_POLICY_UNAVAILABLE');
  cases.push({mode:'cli-missing',exit_code:2,no_origin_printed:true,error_code:failed.stderr.trim()});
  const manifest=JSON.parse(readFileSync(join(build,'dist/build-metadata.json'),'utf8'));
  const policy=manifest.artifact.entries.find(row=>row.path==='src/personal-os-policy.json');assert(policy);
  assert.deepEqual(readFileSync(join(build,'dist/src/personal-os-policy.json')),readFileSync(join(build,'config/personal-os-policy.json')));
  const result={root,build,status:'passed',cases,packaged_policy:policy,artifact_digest:manifest.artifact.digest,
    operational_data_used:false,remote_approval_activated:false,native_model_calls:0};
  writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
}
