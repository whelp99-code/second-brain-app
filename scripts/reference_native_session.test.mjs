import assert from 'node:assert/strict';
import {test} from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,statSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {withPrivateUmask} from './reference_native_session.mjs';
test('native child creates owner-only files and restores parent umask',()=>{
  const root=mkdtempSync(join(tmpdir(),'sb-native-mode-')); const path=join(root,'child'); const original=process.umask();
  try {
    const result=withPrivateUmask(()=>spawnSync(process.execPath,['-e',"require('node:fs').writeFileSync(process.argv[1],'synthetic')",path]));
    assert.equal(result.status,0); assert.equal(statSync(path).mode & 0o777,0o600); assert.equal(process.umask(),original);
  } finally { rmSync(root,{recursive:true}); }
});
test('restores umask when native process setup throws',()=>{
  const original=process.umask(); assert.throws(()=>withPrivateUmask(()=>{throw new Error('spawn failed');}),/spawn failed/);
  assert.equal(process.umask(),original);
});
test('rejects an asynchronous umask callback and restores parent mode',()=>{
  const original=process.umask();
  assert.throws(()=>withPrivateUmask(()=>Promise.resolve()),/Synchronous callback required/);
  assert.equal(process.umask(),original);
});
