"""Parent death cannot release generation ownership before its model child finishes."""
from __future__ import annotations

import fcntl
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from sb.generation_locks import GenerationWriterBusy
from sb.generations import GenerationStore

PARENT = """import json,os,sys
from pathlib import Path
from sb import embedding_session
from sb.embedding_session import ModelSession
from sb.embeddings import ModelIdentity
from sb.generations import GenerationStore
root=Path(sys.argv[1])
release,done=int(sys.argv[2]),int(sys.argv[3])
embedding_session._SCRIPT=(root/'worker.py').read_text()
store=GenerationStore(root/'state',root/'share',provider_instance_id='fixture',provider_release_sha='a'*40)
with store.writer() as lease, lease.preparing():
    os.environ['LOCK_FDS']=json.dumps(lease.child_descriptors)
    os.environ['RELEASE_FD']=str(release)
    os.environ['DONE_FD']=str(done)
    with ModelSession(ModelIdentity('fixture/model','revision',1024),
                      pass_fds=(*lease.child_descriptors,release,done)) as session:
        assert len(session.encode(('fixture',)))==1
        os._exit(17)
"""
WORKER = """import json,os,sys
request=json.loads(sys.stdin.buffer.readline())
response={'id':request['id'],'model':sys.argv[1],'revision':sys.argv[2], 'vectors':[[1.0]+[0.0]*1023]}
print(json.dumps(response),flush=True)
os.read(int(os.environ['RELEASE_FD']),1)
for descriptor in json.loads(os.environ['LOCK_FDS']):
    os.close(descriptor)
os.write(int(os.environ['DONE_FD']),b'x')
"""


def test_model_child_keeps_writer_mutex_after_parent_exit(tmp_path: Path) -> None:
    _ = (tmp_path / "worker.py").write_text(WORKER)
    store = GenerationStore(tmp_path / "state", tmp_path / "share", provider_instance_id="fixture",
                            provider_release_sha="a" * 40)
    release_read, release_write = os.pipe()
    done_read, done_write = os.pipe()
    try:
        result = subprocess.run([sys.executable, "-c", PARENT, str(tmp_path), str(release_read), str(done_write)],
                                pass_fds=(release_read, done_write), capture_output=True, timeout=10, check=False)
        assert result.returncode == 17, result.stderr
        reader = os.open(store.lock_path, os.O_RDWR)
        try:
            fcntl.flock(reader, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(reader)
        with pytest.raises(GenerationWriterBusy), store.try_exclusive():
            pass
        _ = os.write(release_write, b'x')
        with selectors.DefaultSelector() as selector:
            _ = selector.register(done_read, selectors.EVENT_READ)
            assert selector.select(5), "model child did not finish"
            assert os.read(done_read, 1) == b'x'
        with store.try_exclusive():
            pass
    finally:
        # EOF also releases the fixture worker if an assertion above fails.
        for descriptor in (release_read, release_write, done_read, done_write):
            os.close(descriptor)
        store.close()
