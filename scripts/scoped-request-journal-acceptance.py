"""Temporary journal metadata/replay acceptance; not a provider write acceptance."""
import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from sb.request_store import ReplayConflict, RequestStore
from sb.scoped_request_journal import prepare_scoped_journal_entry


def exercise(root, fixture):
    raw = json.loads(fixture.read_text())
    now = datetime.fromisoformat(raw['created_at'])
    entry = prepare_scoped_journal_entry(raw, now=now, expected_provider='provider:fixture')
    store = RequestStore(root, scoped_v4=True)
    try:
        _, replayed = store.accept(entry.identity, {'fixture_metadata_only': True}, now)
        before = tuple(store.db.iterdump())
        try:
            store.accept(replace(entry.identity, scope_digest='sha256:' + '0' * 64), {'fixture_metadata_only': True}, now)
        except ReplayConflict:
            pass
        else:
            raise AssertionError('changed scope accepted')
        assert tuple(store.db.iterdump()) == before
        assert store.get(entry.identity.request_id).identity == entry.identity
        return {'replayed': replayed, 'scope_digest': entry.identity.scope_digest,
                'request_digest': entry.identity.request_digest, 'conflict_preserves_journal': True}
    finally:
        store.close()


def main():
    if sys.argv[1] == '--worker':
        print(json.dumps(exercise(Path(sys.argv[2]), Path(sys.argv[3]))))
        return
    fixture = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='scoped-journal-replay-') as root:
        results = [json.loads(subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
            '--worker', str(Path(root) / 'requests'), str(fixture)], text=True)) for _ in range(2)]
        assert [r['replayed'] for r in results] == [False, True]
        assert results[0]['scope_digest'] == results[1]['scope_digest']
        assert results[0]['request_digest'] == results[1]['request_digest']
        print(json.dumps({'fixture': True, 'independent_processes': 2, 'results': results,
                         'provider_acceptance_completed': False, 'provider_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
