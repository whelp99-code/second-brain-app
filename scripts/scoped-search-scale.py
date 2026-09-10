"""Measure real sealed scoped search over mostly denied synthetic pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import statistics
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
    parser.add_argument('--repetitions', type=int, default=1,
                        help='queries per type on the same generation (1-100); no discarded warmup')
    args = parser.parse_args()
    if not 2 <= args.pages <= 10000:
        parser.error('pages must be between 2 and 10000')
    if not 1 <= args.repetitions <= 100:
        parser.error('repetitions must be between 1 and 100')
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
        for repetition in range(args.repetitions):
            queries = ('ScaleProbe', 'forbidden') if repetition % 2 == 0 else ('forbidden', 'ScaleProbe')
            for query in queries:
                started = time.perf_counter()
                rows = search_scoped_records(generation.root, identity, scope, query, 1)
                elapsed = time.perf_counter() - started
                assert len(rows) == (1 if query == 'ScaleProbe' else 0)
                assert 'forbidden' not in json.dumps(rows)
                observations.append({'query': query, 'repetition': repetition + 1,
                                     'seconds': elapsed, 'rows': len(rows)})
        summaries = []
        for query in ('ScaleProbe', 'forbidden'):
            samples = sorted(row['seconds'] for row in observations if row['query'] == query)
            summaries.append({'query': query, 'samples': len(samples),
                'p50_seconds': statistics.median(samples),
                'p95_seconds': samples[math.ceil(len(samples) * .95) - 1],
                'min_seconds': samples[0], 'max_seconds': samples[-1]})
        result = {'root': str(root), 'pages': args.pages, 'allowed_pages': 1,
                  'repetitions': args.repetitions, 'summaries': summaries,
                  'percentiles': 'p50 median; p95 nearest-rank; all samples including first; alternating query order',
                  'observations': observations, 'peak_process_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'scope': 'synthetic sealed provider library; peak RSS includes build; no MCP/native/concurrent update'}
        (root / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        service.close()


if __name__ == '__main__':
    main()
