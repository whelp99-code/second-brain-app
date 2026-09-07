import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';

// Used only with the isolated acceptance directory marker checked by the child.
export async function pausedCompile({python,sb,config}) {
  const child = spawn(python,['-m','tests.fixtures.generation_compile_worker',config],
    {cwd:sb,stdio:['pipe','pipe','pipe']});
  const lines = createInterface({input:child.stdout});
  const iterator = lines[Symbol.asyncIterator]();
  let stderr = '';
  child.stderr.on('data',chunk=>{stderr=(stderr+chunk).slice(-4096);});
  const exited = new Promise((resolve,reject)=>{
    child.once('error',reject);
    child.once('exit',(code,signal)=>resolve({code,signal}));
  });
  // Attach a handler immediately so a launch error cannot become an unhandled rejection.
  void exited.catch(()=>{});
  const next = async()=>{
    let timer;
    try {
      const row = await Promise.race([iterator.next(),new Promise((_,reject)=>{
        timer=setTimeout(()=>reject(new Error('compiler boundary timed out')),15000);
      })]);
      assert(!row.done,`compiler ended before its boundary: ${stderr}`);
      return JSON.parse(row.value);
    } finally { clearTimeout(timer); }
  };
  const close = async()=>{
    if(child.exitCode===null && child.signalCode===null) child.kill('SIGKILL');
    await exited; lines.close();
  };
  try {
    assert.equal((await next()).event,'preparing');
  } catch(error) { await close(); throw error; }
  return {close,finish:async()=>{
    child.stdin.end('"continue"\n');
    const result = await next();
    assert.equal(result.event,'completed'); assert.equal(result.exit_code,0);
    assert.deepEqual(await exited,{code:0,signal:null});
    lines.close(); return result;
  }};
}
