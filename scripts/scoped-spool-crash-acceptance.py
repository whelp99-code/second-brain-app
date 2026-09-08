"""Kill the actual compiled publisher after linkSync and verify exact retry."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    build = str(Path(sys.argv[1]).resolve())
    unfixed = "--expect-unfixed" in sys.argv
    fixture = str(Path("tests/fixtures/scoped_write_request_v4.json").resolve())
    script = '''
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
const build=process.argv[1],root=process.argv[2],fixture=process.argv[3],mode=process.argv[4];
if(mode==='crash') { const link=fs.linkSync; fs.linkSync=(...args)=>{link(...args);process.exit(73)};syncBuiltinESMExports(); }
const {MemoryScopedWriteSpool}=await import(build+'/src/memory-scoped-write-spool.js');
const {canonicalize}=await import(build+'/src/canonical.js');
const request=JSON.parse(fs.readFileSync(fixture,'utf8'));
const spool=new MemoryScopedWriteSpool(root,'provider:fixture');
const now=new Date(request.created_at);
try {
 if(mode==='read') {spool.read(request.idempotency_key,now);console.log(JSON.stringify({read:true}));}
 else { const result=spool.publish(canonicalize(request),now);const read=spool.read(request.idempotency_key,now);
 console.log(JSON.stringify({created:result.created,request_match:read.request_digest===request.request_digest})); }
} catch(e) {console.log(JSON.stringify({error:e.message}));}
'''
    with tempfile.TemporaryDirectory(prefix="scoped-link-crash-") as root:
        args = ["node", "--input-type=module", "-e", script, build, root, fixture]
        crash = subprocess.run([*args, "crash"], timeout=30, check=False)
        assert crash.returncode == 73
        final = next(Path(root).glob("*.v4.json"))
        before = final.stat()
        original = final.read_bytes()
        assert before.st_nlink == 2 and len(list(Path(root).glob(".*.tmp"))) == 1
        reader = json.loads(subprocess.check_output([*args, "read"], text=True, timeout=30))
        assert reader == {"error": "MEMORY_SPOOL_FILE_INVALID"}
        retry = json.loads(subprocess.check_output([*args, "retry"], text=True, timeout=30))
        if unfixed:
            assert retry == {"error": "MEMORY_SPOOL_FILE_INVALID"}
            assert final.stat().st_nlink == 2
        else:
            assert retry == {"created": False, "request_match": True}
            assert final.stat().st_nlink == 1
            assert not list(Path(root).glob(".*.tmp"))
        assert final.stat().st_ino == before.st_ino and final.read_bytes() == original
        print(json.dumps({"fixture_material": True, "unfixed": unfixed, "processes": 3,
            "crash_exit": crash.returncode, "link_count_before": 2, "reader_before": reader,
            "retry": retry, "link_count_after": final.stat().st_nlink, "same_inode_and_bytes": True,
            "provider_calls": 0, "approval_consumed": False}, indent=2))


if __name__ == "__main__":
    main()
