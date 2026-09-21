from __future__ import annotations

import gzip
from datetime import timedelta
from pathlib import Path

import pytest

from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.effect_write_requests import accept_effect_request
from sb.managed_file_inspection import ManagedInspectionError, inspect_managed_file
from sb.request_executor import RequestExecutor
from sb.runtime_backup import backup_runtime
from tests.task30_effect_factory import effect_request
from tests.test_backup_cancellation_lock_order import config_for
from tests.test_correction_cancellation import CURRENT, HISTORICAL
from tests.test_correction_cancellation_executor import OLD, execute, prepare_unaccepted
from tests.test_request_executor import NOW, _config


def prepare_copies(root: Path, operation: str):
    executor, cancellation, original = prepare_unaccepted(root)
    config = executor.config
    export = effect_request(executor.generations.active(), "export", OLD, NOW + timedelta(seconds=30),
        executor.store.tombstone_high_water(), HISTORICAL, "4")
    accepted = accept_effect_request(config.request_root, export, NOW + timedelta(seconds=31),
        public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
    assert executor.apply_once(now=NOW + timedelta(seconds=31)).state == "proved"
    export_dir = config.export_root / accepted.request_id
    assert export_dir.joinpath("memory.json").is_file()
    archive = config.backup_root / "before.tar.gz"
    backup_runtime(config_for(root), archive)
    assert inspect_managed_file(archive, (OLD.encode(),)).matches > 0
    if operation == "cancel":
        accepted, _ = accept_correction_cancellation(config.request_root, cancellation,
            generations=executor.generations, clock=lambda: NOW + timedelta(minutes=1, seconds=1),
            expected_provider=config.provider_instance_id, historical_delegation_keys=config.jarvis_public_keys,
            current_cancellation_keys={"jarvis:current": CURRENT.public_key()})
        operation_id = accepted["intent_id"]
    else:
        request = original if operation == "correct" else effect_request(executor.generations.active(),
            "forget", OLD, NOW + timedelta(minutes=1), executor.store.tombstone_high_water(), HISTORICAL, "5")
        accepted = accept_effect_request(config.request_root, request, NOW + timedelta(minutes=1, seconds=1),
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
        operation_id = accepted.request_id
    return executor, operation_id, archive, export_dir


def apply(executor, operation, operation_id, barrier=None, *, resume=False):
    if operation == "cancel":
        return execute(executor, operation_id, barrier)
    if barrier is not None:
        class Sink:
            def reach(self, event):
                barrier(event.barrier_id.value)
        executor.barrier_sink = Sink()
    result = executor.apply_once(now=NOW + timedelta(minutes=2, seconds=int(resume)), lease_ms=1)
    return {"state": result.state, "code": result.code}


@pytest.mark.parametrize("operation", ["correct", "forget", "cancel"])
def test_actual_runtime_backup_and_export_disposed_before_pointer(tmp_path: Path, operation: str):
    executor, operation_id, archive, export_dir = prepare_copies(tmp_path, operation)
    base = executor.generations.active()
    phases = []

    def observe(phase):
        phases.append(phase)
        if phase == "pointer_rename":
            assert not archive.exists() and not export_dir.exists()
            assert not archive.with_name(archive.name + ".sha256").exists()
            assert executor.store.db.execute("SELECT count(*) FROM managed_copy_disposals").fetchone()[0] == 1

    try:
        result = apply(executor, operation, operation_id, observe)
        assert result["state"] == ("generation_active" if operation == "cancel" else "proved"), result
        assert phases.index("backup_disposal") < phases.index("pointer_rename")
        assert phases.index("export_disposal") < phases.index("pointer_rename")
        assert not base.root.exists()
        export = executor.store.exports.get(export_dir.name)
        assert export is not None
        assert export.state == "invalidated"
        checkpoint = str(tuple(executor.store.db.execute("SELECT * FROM managed_copy_disposals").fetchone()))
        assert OLD not in checkpoint and str(tmp_path) not in checkpoint
    finally:
        executor.close()


@pytest.mark.parametrize("operation", ["correct", "cancel"])
@pytest.mark.parametrize("alteration", ["none", "missing", "changed"])
def test_recovery_without_original_requires_unchanged_copy_evidence(tmp_path: Path, operation: str, alteration: str):
    executor, operation_id, archive, _export_dir = prepare_copies(tmp_path, operation)
    base = executor.generations.active()

    def interrupt(phase):
        if phase == "predecessor_disposal":
            raise KeyboardInterrupt()

    try:
        with pytest.raises(KeyboardInterrupt):
            apply(executor, operation, operation_id, interrupt)
        assert not base.root.exists() and not archive.exists()
        if alteration == "missing":
            executor.store.db.execute("DELETE FROM managed_copy_disposals")
        elif alteration == "changed":
            archive.write_bytes(gzip.compress(OLD.encode()))
    finally:
        executor.close()
    restarted = RequestExecutor(_config(tmp_path))
    try:
        if alteration != "none":
            code = "MANAGED_DISPOSAL_EVIDENCE_MISSING" if alteration == "missing" else "MANAGED_DISPOSAL_INVENTORY_CHANGED"
            if operation == "cancel":
                with pytest.raises(ManagedInspectionError, match=code):
                    apply(restarted, operation, operation_id, resume=True)
            else:
                result = apply(restarted, operation, operation_id, resume=True)
                assert result["state"] == "reconciling" and result["code"] == code, result
        else:
            result = apply(restarted, operation, operation_id, resume=True)
            assert result["state"] == ("generation_active" if operation == "cancel" else "proved"), result
    finally:
        restarted.close()


@pytest.mark.parametrize("operation", ["correct", "cancel"])
def test_new_backup_before_pointer_is_rescanned_on_retry(tmp_path: Path, operation: str):
    executor, operation_id, archive, _export_dir = prepare_copies(tmp_path, operation)
    base = executor.generations.active()

    def interrupt(phase):
        if phase == "disposal_parent_fsync":
            raise KeyboardInterrupt()

    try:
        with pytest.raises(KeyboardInterrupt):
            apply(executor, operation, operation_id, interrupt)
        assert base.root.exists() and not archive.exists()
        assert executor.store.db.execute("SELECT count(*) FROM managed_copy_disposals").fetchone()[0] == 1
    finally:
        executor.close()
    backup_runtime(config_for(tmp_path), archive)
    assert inspect_managed_file(archive, (OLD.encode(),)).matches > 0
    restarted = RequestExecutor(_config(tmp_path))
    try:
        result = apply(restarted, operation, operation_id, resume=True)
        assert result["state"] == ("generation_active" if operation == "cancel" else "proved"), result
        assert not archive.exists() and not base.root.exists()
    finally:
        restarted.close()


def test_forget_does_not_dispose_unmanaged_client_session_copy(tmp_path: Path) -> None:
    session = tmp_path / "client-home" / ".claude" / "projects" / "demo" / "session.jsonl"
    session.parent.mkdir(parents=True)
    payload = b'{"type":"user","message":{"content":"' + OLD.encode() + b'"}}\n'
    session.write_bytes(payload)
    executor, operation_id, archive, export_dir = prepare_copies(tmp_path, "forget")
    try:
        result = apply(executor, "forget", operation_id)
        assert result["state"] == "proved", result
        assert session.is_file()
        assert session.read_bytes() == payload
        assert not archive.exists()
        assert not export_dir.exists()
    finally:
        executor.close()
