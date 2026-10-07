"""Unpublished batch work must not replace the active managed generation."""
import multiprocessing
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from multiprocessing.synchronize import Event
from pathlib import Path

from sb.config import Config, TomlValue
from sb.generation_runtime import GenerationMutationService
from sb.ops import status_snapshot
from sb.pipeline import StageFn, StageReport, run_all
from sb.store.ledger import Ledger
from sb.vault import Vault
from tests.test_runtime_reliability import managed


def _blocked_managed_batch(raw: Mapping[str, TomlValue], ready: Event, release: Event):
    from sb import pipeline

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        ready.set()
        _ = release.wait(30)
        return pipeline.StageReport((), 0, 0, 0, False)

    def ingest(config: Config, source_ids: Sequence[str] | None, limit: int | None) -> StageFn:
        del config, source_ids, limit
        return stage

    pipeline.ingest = ingest
    _ = pipeline.run_all(Config(raw=raw))


def test_unpublished_killed_batch_preserves_active_input_and_recovers(tmp_path: Path):
    config = Config(raw={**managed(tmp_path).raw, 'sources': []})
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember('합성 기억 원본 보존', 'crash-baseline', datetime.now(UTC))
    finally:
        service.close()
    active = Path(config.vault_root)
    before = active.resolve()
    pending = {p.relative_to(before).as_posix(): p.read_bytes() for p in (before / 'inbox').rglob('*.md')}
    assert len(pending) == 1
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_blocked_managed_batch, args=(config.raw, ready, release))
    child.start()
    try:
        assert ready.wait(10)
        assert active.resolve() == before
        assert status_snapshot(config)['last_batch'] is None
        assert run_all(config).already_running
        child.kill()
        child.join(10)
        assert child.exitcode is not None and child.exitcode != 0
        assert active.resolve() == before
        assert all((active / rel).read_bytes() == data for rel, data in pending.items())
        assert run_all(config).status == 'ok'
        assert active.resolve() != before
        assert all((active / rel).read_bytes() == data for rel, data in pending.items())
        snapshot = status_snapshot(config)
        assert isinstance(snapshot['last_batch'], dict)
        assert snapshot['last_batch']['status'] == 'ok'
        staging = Path(config.share_root) / 'vault-generations/.staging'
        assert staging.is_dir() and list(staging.iterdir()) == []
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)


def _blocked_published_batch(raw: Mapping[str, TomlValue], phase: str, ready: Event, release: Event):
    from sb.generations import Generation, GenerationStore
    original = GenerationStore.activate

    def pause_at_phase(observed: str) -> None:
        if observed == phase:
            ready.set()
            _ = release.wait(30)

    def activate(self: GenerationStore, generation: Generation, expected_parent: Generation | None,
                 now: datetime, *, barrier: Callable[[str], None] | None = None,
                 lock_held: bool = False) -> None:
        del barrier
        original(self, generation, expected_parent, now, barrier=pause_at_phase, lock_held=lock_held)

    GenerationStore.activate = activate
    _ = run_all(Config(raw=raw))


def _published_crash_case(tmp_path: Path, phase: str):
    config = Config(raw={**managed(tmp_path).raw, 'sources': []})
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember('공개 후 원본 보존 검증', 'published-crash', datetime.now(UTC))
    finally:
        service.close()
    active = Path(config.vault_root)
    before = active.resolve()
    pending = {p.relative_to(before).as_posix(): p.read_bytes() for p in (before / 'inbox').rglob('*.md')}
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_blocked_published_batch, args=(config.raw, phase, ready, release))
    child.start()
    try:
        assert ready.wait(10)
        published = active.resolve()
        assert published != before
        completed = status_snapshot(config)['last_batch']
        assert isinstance(completed, dict)
        assert completed['status'] == 'ok'
        child.kill()
        child.join(10)
        assert child.exitcode is not None and child.exitcode != 0
        service = GenerationMutationService.from_config(config)
        try:
            _ = service.maintain(datetime.now(UTC))
            _ = service.maintain(datetime.now(UTC))
        finally:
            service.close()
        assert active.resolve() == published
        assert status_snapshot(config)['last_batch'] == completed
        assert not before.exists()
        assert all((active / rel).read_bytes() == data for rel, data in pending.items())
        return {'phase': phase, 'batch': completed, 'same_published_generation': True,
                'predecessor_disposed': True, 'pending_files': len(pending)}
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)


def test_pointer_switch_crash_recovers_without_repeating_batch(tmp_path: Path):
    for phase in ('pointer_rename', 'activation_verify'):
        _ = _published_crash_case(tmp_path / phase, phase)
