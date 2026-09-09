"""A new single writer may retire an unfinished batch after the old writer exits."""
import multiprocessing
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.config import Config
from sb.ops import status_snapshot
from sb.pipeline import _run_all_mutable
from sb.vault import init_vault


def _blocked_batch(root: str, ready, release, after_ingest: bool):
    from sb import pipeline

    def stage(*args):
        ready.set()
        release.wait(30)
        return pipeline.StageReport((), 0, 0, 0, False)

    if after_ingest:
        pipeline._ingest = lambda *args: lambda *unused: pipeline.StageReport((), 0, 1, 3, False)
        pipeline._compile_stage = lambda *args: stage
    else:
        pipeline._ingest = lambda *args: stage
    pipeline._run_all_mutable(Config(raw={'vault_root': root, 'sources': []}))


@pytest.mark.parametrize("after_ingest", [False, True])
def test_killed_batch_is_interrupted_only_after_next_writer_acquires_lock(tmp_path: Path, after_ingest: bool):
    root = tmp_path / 'vault'
    init_vault(root)
    config = Config(raw={'vault_root': str(root), 'sources': []})
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_blocked_batch, args=(str(root), ready, release, after_ingest))
    child.start()
    try:
        assert ready.wait(10)
        first = status_snapshot(config)['last_batch']
        assert first['status'] == 'running' and first['finished_at'] is None
        assert first['stages_attempted'] == int(after_ingest)
        assert first['errors'] == int(after_ingest)
        assert _run_all_mutable(config).already_running
        assert status_snapshot(config)['last_batch'] == first
        child.kill()
        child.join(10)
        assert child.exitcode is not None and child.exitcode != 0
        assert status_snapshot(config)['last_batch']['status'] == 'running'
        result = _run_all_mutable(config)
        assert result.status == 'ok'
        with closing(sqlite3.connect(root / '.sb/ledger.db')) as connection:
            old = connection.execute('SELECT status,finished_at,attempted,errors,detail FROM run_stage WHERE run_id=? AND stage=?',
                                     (first['run_id'], 'batch')).fetchone()
        assert old[0] == 'interrupted' and old[1] is not None
        assert old[2] == int(after_ingest) and old[3] == int(after_ingest)
        if after_ingest:
            assert '"stage":"ingest"' in old[4] and '"status":"partial"' in old[4]
        assert status_snapshot(config)['last_batch']['status'] == 'ok'
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
