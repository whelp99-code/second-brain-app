from __future__ import annotations

import hashlib
import signal
import subprocess
import sys

import pytest

from sb.request_executor import RequestExecutor
from sb.restore_models import RestoreProofV1
from tests.task30_restore_factory import OLD, restore_fixture


@pytest.mark.parametrize('phase', ['extract', 'materialize'])
def test_restore_sigkill_preserves_active_and_allows_fresh_process_retry(tmp_path, phase):
    fixture = restore_fixture(tmp_path, full_source=True)
    config = fixture.executor.config
    active = fixture.executor.generations.active()
    before = hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest()
    high_water = fixture.executor.store.tombstone_high_water()
    (tmp_path / 'restore-request.json').write_text(fixture.request.model_dump_json())
    fixture.executor.close()
    command = [sys.executable, '-m', 'tests.restore_kill_worker', str(tmp_path)]
    killed = subprocess.run([*command, phase], capture_output=True, text=True, timeout=30, check=False)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    assert not (tmp_path / 'restore-result.json').exists()
    recovered = subprocess.run([*command, 'retry'], capture_output=True, text=True, timeout=30, check=False)
    assert recovered.returncode == 0, recovered.stderr
    proof = RestoreProofV1.model_validate_json((tmp_path / 'restore-result.json').read_text())
    restarted = RequestExecutor(config)
    try:
        assert restarted.generations.active().generation_id == active.generation_id
        assert hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest() == before
        assert restarted.store.tombstone_high_water() == high_water
        assert proof.blocked_matches == 0 and proof.scan_errors == 0
        candidate = restarted.generations.generations / proof.result_generation_id
        assert candidate.is_dir()
        assert all(OLD.encode() not in path.read_bytes()
                   for path in candidate.rglob('*') if path.is_file())
        assert not list(restarted.generations.staging.iterdir())
        assert not list((tmp_path / "restore").iterdir())
    finally:
        restarted.close()
