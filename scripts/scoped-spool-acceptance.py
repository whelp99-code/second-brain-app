"""Independent compiled JARVIS spool publication/read/replay acceptance."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    build = str(Path(sys.argv[1]).resolve())
    fixture = str(Path("tests/fixtures/scoped_write_request_v4.json").resolve())
    script = '''
import {readFileSync,statSync} from 'node:fs';
const build=process.argv[1], root=process.argv[2], fixture=process.argv[3], mode=process.argv[4];
const {MemoryScopedWriteSpool}=await import(build+'/src/memory-scoped-write-spool.js');
const {canonicalize}=await import(build+'/src/canonical.js');
const value=JSON.parse(readFileSync(fixture,'utf8'));
const spool=new MemoryScopedWriteSpool(root,'provider:fixture');
const now=new Date(value.created_at);
if(mode==='publish-crash') {spool.publish(canonicalize(value),now);process.exit(73);}
const read=spool.read(value.idempotency_key,now);
const before=statSync(root+'/'+value.idempotency_key.slice(-64)+'.v4.json').ino;
const publication=spool.publish(canonicalize(value),now);
console.log(JSON.stringify({created:publication.created,request_match:read.request_digest===value.request_digest,
 body_match:read.preparation.payload.content===value.preparation.payload.content,
 same_inode:before===statSync(publication.path).ino,file_mode:statSync(publication.path).mode&511}));
'''
    with tempfile.TemporaryDirectory(prefix="scoped-spool-") as root:
        args = ["node", "--input-type=module", "-e", script, build, root, fixture]
        crash = subprocess.run([*args, "publish-crash"], timeout=30, check=False)
        assert crash.returncode == 73
        replay = json.loads(subprocess.check_output([*args, "read-replay"], text=True, timeout=30))
        assert replay == {"created": False, "request_match": True, "body_match": True, "same_inode": True, "file_mode": 384}
        os.mkfifo(Path(root) / "fifo", 0o600)
        fifo_script = '''
const {inspectPrivateSpoolRoot,readPrivateSpoolFile}=await import(process.argv[1]+'/src/memory-private-spool-files.js');
try{readPrivateSpoolFile(inspectPrivateSpoolRoot(process.argv[2]),process.argv[2]+'/fifo',32768);process.exit(1)}
catch(e){console.log(e.message)}
'''
        fifo = subprocess.check_output(["node", "--input-type=module", "-e", fifo_script, build, root], text=True, timeout=5).strip()
        assert fifo == "MEMORY_SPOOL_FILE_INVALID"
        print(json.dumps({"fixture_material": True, "processes": 3, "publication_exit": crash.returncode,
            "replay": replay, "fifo": fifo, "provider_calls": 0, "approval_consumed": False,
            "outbox_enqueued": False}, indent=2))


if __name__ == "__main__":
    main()
