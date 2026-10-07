"""A new single writer may retire an unfinished batch after the old writer exits."""
import multiprocessing
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.config import Config
from sb.effect_values import JsonValue, is_json_object
from sb.ops import status_snapshot
from sb.pipeline import StageFn, StageReport, run_all_mutable
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault


def _blocked_batch(root: str, ready: Event, release: Event, after_ingest: bool):
    from sb import pipeline

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        ready.set()
        _ = release.wait(30)
        return pipeline.StageReport((), 0, 0, 0, False)

    def completed(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 1, 3, False)

    def ingest(config: Config, source_ids: Sequence[str] | None, limit: int | None) -> StageFn:
        del config, source_ids, limit
        return completed if after_ingest else stage

    def compile_stage(config: Config, llm_mode: str) -> StageFn:
        del config, llm_mode
        return stage

    pipeline.ingest = ingest
    if after_ingest:
        pipeline.compile_stage = compile_stage
    _ = pipeline.run_all_mutable(Config(raw={'vault_root': root, 'sources': []}))


@pytest.mark.parametrize("after_ingest", [False, True])
def test_killed_batch_is_interrupted_only_after_next_writer_acquires_lock(tmp_path: Path, after_ingest: bool):
    root = tmp_path / 'vault'
    _ = init_vault(root)
    config = Config(raw={'vault_root': str(root), 'sources': []})
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_blocked_batch, args=(str(root), ready, release, after_ingest))
    child.start()
    try:
        assert ready.wait(10)
        first = status_snapshot(config)['last_batch']
        assert isinstance(first, dict) and is_json_object(TypeAdapter[JsonValue](JsonValue).validate_python(first, strict=True))
        assert first['status'] == 'running' and first['finished_at'] is None
        assert first['stages_attempted'] == int(after_ingest)
        assert first['errors'] == int(after_ingest)
        assert run_all_mutable(config).already_running
        assert status_snapshot(config)['last_batch'] == first
        child.kill()
        child.join(10)
        assert child.exitcode is not None and child.exitcode != 0
        running = status_snapshot(config)['last_batch']
        assert isinstance(running, dict) and is_json_object(TypeAdapter[JsonValue](JsonValue).validate_python(running, strict=True))
        assert running['status'] == 'running'
        result = run_all_mutable(config)
        assert result.status == 'ok'
        with closing(sqlite3.connect(root / '.sb/ledger.db')) as connection:
            cursor = connection.execute('SELECT status,finished_at,attempted,errors,detail FROM run_stage WHERE run_id=? AND stage=?',
                                     (first['run_id'], 'batch'))
            old = TypeAdapter[tuple[str, str | None, int, int, str]](
                tuple[str, str | None, int, int, str],
            ).validate_python(cursor.fetchone(), strict=True)
        assert old[0] == 'interrupted' and old[1] is not None
        assert old[2] == int(after_ingest) and old[3] == int(after_ingest)
        if after_ingest:
            assert '"stage":"ingest"' in old[4] and '"status":"partial"' in old[4]
        completed = status_snapshot(config)['last_batch']
        assert isinstance(completed, dict) and is_json_object(TypeAdapter[JsonValue](JsonValue).validate_python(completed, strict=True))
        assert completed['status'] == 'ok'
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
