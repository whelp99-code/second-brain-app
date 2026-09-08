// Inspect only a completed synthetic native-session acceptance fixture.
import assert from 'node:assert/strict';
import {existsSync,lstatSync,readFileSync,readdirSync,realpathSync,rmSync,writeFileSync} from 'node:fs';
import {basename,dirname,join,resolve} from 'node:path';
assert(process.argv.length===3 || (process.argv.length===4 && process.argv[3]==='--dispose-native-state'));
const resultPath=realpathSync(process.argv[2]);
const result=JSON.parse(readFileSync(resultPath,'utf8'));
assert(result.native_session===true && result.fixture_origin==='synthetic');
assert(result.status==='native_model_consumed_reference');
const root=realpathSync(result.root); assert(dirname(resultPath)===root && basename(root).startsWith('sb-reference-model-'));
assert((lstatSync(root).mode & 0o077)===0);
const nativeHome=resolve(result.native_session_fixture.native_home);
assert(nativeHome===join(root,'native-codex') && realpathSync(nativeHome)===nativeHome);
const expectedIds=new Set(result.native_session_fixture.calls.map(call=>call.thread_id));
const answers=[result.positive.response.answer,result.corrected_model.response.answer];
assert(answers.every(answer=>typeof answer==='string' && /^[0-9a-f]{32}$/.test(answer)));
const calls=result.native_session_fixture.calls;
assert(calls.length===10 && expectedIds.size===5);
for (const id of expectedIds) {
  const pair=calls.filter(call=>call.thread_id===id);
  assert(pair.length===2 && pair[0].expected_thread_id===null && pair[1].expected_thread_id===id);
}
const files=[]; const objects=[]; const seen=new Set(); let totalBytes=0;
function scan(directory) {
  const directoryInfo=lstatSync(directory); assert(directoryInfo.isDirectory() && !directoryInfo.isSymbolicLink());
  objects.push({kind:'directory',private_mode:(directoryInfo.mode & 0o077)===0});
  assert(objects.length<=5000);
  for(const entry of readdirSync(directory,{withFileTypes:true})) {
    assert(!entry.isSymbolicLink()); const path=join(directory,entry.name);
    if(entry.isDirectory()) scan(path);
    else {
      assert(entry.isFile()); const info=lstatSync(path);
      totalBytes+=info.size; assert(info.size<=32*1024*1024 && totalBytes<=128*1024*1024 && objects.length<5000);
      const content=readFileSync(path);
      const observation={kind:'file',relative_path:path.slice(nativeHome.length+1),bytes:info.size,private_mode:(info.mode & 0o077)===0,
        original_answer_present:content.includes(Buffer.from(answers[0])),corrected_answer_present:content.includes(Buffer.from(answers[1]))};
      objects.push(observation);
      if(path.startsWith(join(nativeHome,'sessions')+'/') && entry.name.endsWith('.jsonl')) {
        const match=/^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$/.exec(entry.name);
        assert(match && expectedIds.has(match[1]) && !seen.has(match[1]),'Unexpected or repeated native session file');
        seen.add(match[1]); files.push({session_id:match[1],...observation});
      }
    }
  }
}
scan(nativeHome);
assert(files.length===5);
assert(files.some(file=>file.original_answer_present),'Expected persisted original reference evidence');
assert(files.some(file=>file.corrected_answer_present),'Expected persisted corrected reference evidence');
const report={status:objects.every(file=>file.private_mode) ? 'passed' : 'nonprivate_native_file_modes',provider_final_records:result.fresh_read_after_retained_probe,
  native_objects:objects.length,native_bytes:totalBytes,nonprivate_objects:objects.filter(item=>!item.private_mode).length,
  all_native_file_canary_matches:objects.filter(item=>item.original_answer_present || item.corrected_answer_present).length,
  canary_surfaces:objects.filter(item=>item.original_answer_present || item.corrected_answer_present),
  retained_original_sessions:files.filter(file=>file.original_answer_present).length,
  retained_corrected_sessions:files.filter(file=>file.corrected_answer_present).length,files,
  native_state_disposed:false,all_fixture_plaintext_disposed:false,auth_mount_read_only:result.native_session_fixture.auth_read_only};
assert.equal(report.provider_final_records,0);
if(process.argv[3]==='--dispose-native-state') {
  rmSync(nativeHome,{recursive:true}); assert(!existsSync(nativeHome)); report.native_state_disposed=true;
}
writeFileSync(join(root,'native-storage-audit.json'),JSON.stringify(report,null,2),{mode:0o600});
process.stdout.write(JSON.stringify(report,null,2)+'\n');

if (report.status!=='passed') process.exitCode=1;
