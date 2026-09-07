from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from pytest import MonkeyPatch

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import GenerationOperation, generation_runtime_paths
from sb.llm import LLMUnavailable
from sb.ops import restore_backup
from sb.pipeline import run_compile, run_ingest
from sb.runtime_access import mutate_root
from sb.runtime_backup import backup_runtime
from sb.search import SearchIndex
from sb.store.ledger import load_ledger_tables
from sb.uploads import accept_upload


def managed(tmp_path: Path) -> Config:
    return Config(raw={
        "vault_root": str(tmp_path / "share" / "vault"),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "export_root": str(tmp_path / "exports"),
        "backup_root": str(tmp_path / "backups"),
        "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "allow"}],
    })


def test_managed_capture_compile_short_search_backup_restore(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("업무 기억 보존 검증", "기억", datetime.now(UTC))
    finally:
        service.close()
    active = Path(config.vault_root)
    assert active.is_symlink()
    assert generation_runtime_paths(config).active == active
    receipt = mutate_root(config, GenerationOperation.INBOX, lambda root: accept_upload(
        root, "note.md", "추가 업무 기억".encode(), device_id="test", relative_path="note.md",
    ))
    assert receipt.state == "queued"
    assert run_ingest(config, ("inbox",)).exit_code == 0
    class CitedKorean:
        def generate(self, prompt: str, *, system: str | None = None,
                     json_mode: bool = False, timeout: int = 120) -> str:
            if json_mode:
                return '{"verdict":"compatible","confidence":1,"rationale":"independent facts"}'
            sid = re.search(r"sid=([0-9a-f]{8})", prompt)
            assert sid is not None
            return f"업무 기억 보존 검증.[^{sid.group(1)}]"
    monkeypatch.setattr("sb.pipeline._llm", lambda *_args: CitedKorean())
    assert run_compile(config, llm_mode="fake").exit_code == 0
    index = active / ".sb" / "search.db"
    before = hashlib.sha256(index.read_bytes()).hexdigest()
    hits = SearchIndex(active).search("업무", 100)
    assert hits
    assert hashlib.sha256(index.read_bytes()).hexdigest() == before
    backup = backup_runtime(config, tmp_path / "backup.tar.gz")
    restored = tmp_path / "restored"
    _ = restore_backup(backup.archive, restored)
    assert (restored / ".recovery" / "requests" / "journal.db").is_file()
    assert SearchIndex(restored).search("업무", 100) == hits


def test_llm_outage_is_failed_and_retryable(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("Remember outage evidence", "outage", datetime.now(UTC))
    finally:
        service.close()
    assert run_ingest(config, ("inbox",)).exit_code == 0

    class Offline:
        def generate(self, prompt: str, *, system: str | None = None,
                     json_mode: bool = False, timeout: int = 120) -> str:
            raise LLMUnavailable(attempts=1, reason="synthetic outage")

    monkeypatch.setattr("sb.pipeline._llm", lambda *_args: Offline())
    outcome = run_compile(config)
    assert outcome.status == "failed" and outcome.exit_code == 1 and outcome.errors > 0
    tables = load_ledger_tables(Path(config.vault_root) / ".sb" / "ledger.db")
    assert any(row.status == "failed" for row in tables.derivations.values())


def test_readiness_closes_ledger_before_next_generation(tmp_path: Path) -> None:
    import gc

    from sb.readiness import readiness

    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    enabled = gc.isenabled()
    try:
        _ = service.remember("First memory", "first", datetime.now(UTC))
        gc.disable()  # Connection lifetime must never depend on garbage collection.
        report = readiness(config)
        checks = report["checks"]
        assert isinstance(checks, dict) and checks["readable"] is True
        _ = service.remember("Second memory", "second", datetime.now(UTC))
    finally:
        if enabled:
            gc.enable()
        service.close()


def test_pending_inbox_survives_retry_and_capped_ingest(tmp_path: Path) -> None:
    from sb.ops import retry_failed

    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("first pending evidence", "first", datetime.now(UTC))
        _ = service.remember("second pending evidence", "second", datetime.now(UTC))
    finally:
        service.close()
    active = Path(config.vault_root)
    expected = {p.name: p.read_bytes() for p in (active / "inbox").glob("*.md")}
    assert len(expected) == 2
    assert mutate_root(config, GenerationOperation.EFFECT, retry_failed) == 0
    assert {p.name: p.read_bytes() for p in (active / "inbox").glob("*.md")} == expected
    first = run_ingest(config, ("inbox",), limit=1)
    assert first.status == "capped"
    assert len(list((active / "inbox").glob("*.md"))) == 1
    assert len(load_ledger_tables(active / ".sb/ledger.db").source_items) == 1
    assert run_ingest(config, ("inbox",), limit=1).exit_code == 0
    assert not list((active / "inbox").glob("*.md"))
    tables = load_ledger_tables(active / ".sb/ledger.db")
    assert len(tables.source_items) == 2
    assert len(tables.units) == 2


def test_cas_failure_preserves_input_for_later_ingest(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("evidence that must survive CAS failure", "cas", datetime.now(UTC))
    finally:
        service.close()
    active = Path(config.vault_root)
    expected = {p.name: p.read_bytes() for p in (active / "inbox").glob("*.md")}

    def fail_put(_self: object, _data: bytes) -> str:
        raise OSError("synthetic CAS failure")

    with monkeypatch.context() as patch:
        patch.setattr("sb.pipeline.ContentAddressedStore.put", fail_put)
        assert run_ingest(config, ("inbox",)).exit_code == 1
    assert {p.name: p.read_bytes() for p in (active / "inbox").glob("*.md")} == expected
    assert not load_ledger_tables(active / ".sb/ledger.db").source_items
    assert run_ingest(config, ("inbox",)).exit_code == 0
    assert len(load_ledger_tables(active / ".sb/ledger.db").source_items) == 1
    assert not list((active / "inbox").glob("*.md"))
