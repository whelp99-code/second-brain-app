"""Measure real sealed scoped search over mostly denied synthetic pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.remember_page import materialize_remember
from sb.scoped_search import search_scoped_records
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=int, default=100)
    args = parser.parse_args()
    if not 2 <= args.pages <= 10000:
        parser.error('pages must be between 2 and 10000')
    root = Path(tempfile.mkdtemp(prefix='sb-scoped-scale-', dir='/var/tmp'))
    config = Config(raw={'vault_root': str(root / 'share/vault'), 'share_root': str(root / 'share'),
                        'state_root': str(root / 'state'), 'request_root': str(root / 'requests'),
                        'export_root': str(root / 'exports'), 'knowledge_registry': str(root / 'registry.sqlite')})
    service = GenerationMutationService.from_config(config)
    now = datetime.now(UTC)
    scope = SourceAccess('principal:owner', ('project:allowed',), 'policy:1')
    denied = SourceAccess('principal:owner', ('project:denied',), 'policy:1')

    def seed(folder):
        for number in range(args.pages):
            materialize_remember(folder, content=f'ScaleProbe {number} ' + ('permitted' if number == args.pages - 1 else 'forbidden'),
                candidate_id='memcand:pos:v1:' + hashlib.sha256(str(number).encode()).hexdigest(),
                created_at=now.isoformat(), release_sha='a' * 40,
                source_access=scope if number == args.pages - 1 else denied)

    try:
        generation = service.mutate(GenerationMutation('scale:seed', GenerationOperation.REMEMBER,
            now, GenerationAuthority(None, None), seed)).generation
        identity = GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
            generation.manifest.generation_digest, generation.head, generation.tree)
        observations = []
        for query in ('ScaleProbe', 'forbidden'):
            started = time.perf_counter()
            rows = search_scoped_records(generation.root, identity, scope, query, 1)
            elapsed = time.perf_counter() - started
            assert len(rows) == (1 if query == 'ScaleProbe' else 0)
            assert 'forbidden' not in json.dumps(rows)
            observations.append({'query': query, 'seconds': elapsed, 'rows': len(rows)})
        result = {'root': str(root), 'pages': args.pages, 'allowed_pages': 1,
                  'observations': observations, 'peak_process_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'scope': 'synthetic sealed provider library; peak RSS includes build; no MCP/native/concurrent update'}
        (root / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        service.close()


if __name__ == '__main__':
    main()
