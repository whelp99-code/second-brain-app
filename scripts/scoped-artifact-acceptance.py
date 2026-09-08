"""Isolated writer plus independent readers; no production authority or transport."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from sb.generations import GenerationStore
from sb.memory_access import MemoryAccessError
from sb.remember_page import materialize_remember
from sb.scoped_remember_artifact import read_scoped_remember_artifact
from sb.scoped_write_request import parse_scoped_write_request
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1

raw = json.loads(Path('tests/fixtures/scoped_write_request_v4.json').read_text())
now = datetime.fromisoformat(raw['created_at'])
request = parse_scoped_write_request(raw, now=now, expected_provider=raw['provider_instance_id'])

if len(sys.argv) > 1:
    root = Path(sys.argv[1])
    manifest = json.loads((root / 'generation.json').read_text())
    identity = GenerationIdentityV1(*(manifest[key] for key in (
        'provider_instance_id', 'generation_id', 'generation_digest', 'head', 'tree')))
    try:
        page = read_scoped_remember_artifact(root, identity, request,
            SourceAccess('principal:owner', (sys.argv[2],), 'policy:fixture'))
        print(json.dumps({'generation_id': identity.generation_id, 'records': len(page.records),
            'record_ids': [row.record_id for row in page.records]}))
    except MemoryAccessError as exc:
        print(json.dumps({'denied': str(exc)}))
else:
    temporary = Path(tempfile.mkdtemp(prefix='scoped-artifact-'))
    store = GenerationStore(temporary / 'state', temporary / 'share',
        provider_instance_id=request.provider_instance_id, provider_release_sha='a' * 40)
    try:
        generations = []
        for index in range(2):
            generation = store.build(request_id=f'fixture:{index}', parent=None if not generations else generations[-1],
                tombstone_sequence=0, tombstone_set_root='sha256:' + '0' * 64,
                created_at=now, allowed=lambda _: True,
                mutate=lambda root: materialize_remember(root,
                    content=request.preparation.content if index == 0 else '후속 기억',
                    candidate_id=raw['source_request']['candidate_id'] if index == 0 else 'memcand:pos:v1:' + 'd' * 64,
                    created_at=raw['created_at'], release_sha='a' * 40,
                    sensitivity=request.preparation.sensitivity, source_access=request.preparation.source_access))
            generations.append(generation)
        results = [json.loads(subprocess.check_output([sys.executable, __file__, str(g.root), project],
            text=True, timeout=30)) for g in generations for project in ('project:shared-memory', 'project:other')]
        assert results[0]['records'] == results[2]['records'] == 4
        assert results[0]['record_ids'] == results[2]['record_ids']
        assert results[0]['generation_id'] != results[2]['generation_id']
        assert results[1]['denied'] == results[3]['denied'] == 'MEMORY_ACCESS_DENIED'
        print(json.dumps({'fixture': True, 'independent_read_processes': 4,
            'successor_preserves_artifact': True, 'results': results}, indent=2))
    finally:
        store.close()
        for directory, dirs, files in os.walk(temporary):
            Path(directory).chmod(0o700)
            for name in dirs + files:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(temporary)
