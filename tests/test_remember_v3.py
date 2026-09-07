"""Ordinary multiline remember through the real journal, executor and restore."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

import pytest

from sb.config import Config
from sb.mcp_contract import write_fixture_request
from sb.mcp_remember_contract import remember_fixture_request
from sb.memory_records import records_for_page
from sb.ops import restore_backup
from sb.pipeline import audit_citations
from sb.remember_body import plain_text_body
from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.runtime_backup import backup_runtime
from sb.stable_requests import request_value
from sb.targets import GenerationIdentityV1
from sb.task30_barriers import BarrierEvent
from sb.write_request_values import (
    WriteRequestRejected,
    canonical_bytes,
    parse_remember_envelope,
)
from sb.write_requests import accept_memory_write_request
from tests.task30_process_harness import NOW, executor_config


@pytest.mark.parametrize("content", [
    " \n첫\t결정\r\n\r\n 반복 \r반복\n[^user]\n",
    "\ufeff첫 결정\n둘째 결정", "\u0085첫 결정\n둘째 결정",
    "\n".join(["반복"] * 64),
])
def test_multiline_v3_is_proved_cited_replayed_and_restorable(tmp_path: Path, content: str) -> None:
    config = executor_config(tmp_path)
    request = remember_fixture_request(content)
    original = canonical_bytes(request)
    accepted = accept_memory_write_request(config.share_root / "vault", config.request_root, request, NOW)
    assert accepted.schema_version == 3 and not accepted.replayed
    pending = config.request_root / "pending" / f"{accepted.request_id}.v3.json"
    envelope = parse_remember_envelope(pending.read_bytes())
    assert envelope.schema_version == 3
    assert request_value(envelope.request) == request
    assert envelope.request.payload["content"] == content
    with pytest.raises(WriteRequestRejected):
        # An envelope may not be silently reinterpreted as V1.
        _ = parse_remember_envelope(pending.read_bytes().replace(b'"schema_version":3', b'"schema_version":1'))
    executor = RequestExecutor(config)
    try:
        result = executor.apply_once(now=NOW)
        assert result.state == "proved", result
        assert result.request_id == accepted.request_id
        generation = executor.generations.active()
        page = next((generation.root / "wiki").glob("memory-*.md"))
        identity = GenerationIdentityV1(config.provider_instance_id, generation.generation_id,
                                        generation.manifest.generation_digest, generation.head, generation.tree)
        records = records_for_page(generation.root, str(page.relative_to(generation.root))[:-3], identity)
        expected = [line.strip() for line in content.replace("[^", "\\[\\^").splitlines() if line.strip()]
        assert [record.record_text for record in records] == expected
        assert len({record.record_id for record in records}) == len(expected)
        assert audit_citations(generation.root) == ()
        raw = tuple((generation.root / "raw").glob("*/*"))
        assert len(raw) == 1 and raw[0].read_bytes() == content.encode("utf-8")
        assert raw[0].name == hashlib.sha256(content.encode()).hexdigest()
        replay = accept_memory_write_request(config.share_root / "vault", config.request_root, request, NOW)
        assert asdict(replay) == {**asdict(accepted), "replayed": True}
        assert executor.apply_once(now=NOW).state == "idle"
        backup = tmp_path / "v3.tar.gz"
        _ = backup_runtime(Config(raw={
            "vault_root": str(config.share_root / "vault"),
            "state_root": str(config.state_root), "share_root": str(config.share_root),
            "request_root": str(config.request_root), "export_root": str(config.export_root),
            "backup_root": str(config.backup_root),
            "provider_instance_id": config.provider_instance_id,
        }), backup)
        restored = tmp_path / "restored"
        _ = restore_backup(backup, restored)
        assert next((restored / "raw").glob("*/*")).read_bytes() == content.encode()
        assert (restored / page.relative_to(generation.root)).read_bytes() == page.read_bytes()
        assert audit_citations(restored) == ()
        assert canonical_bytes(request) == original
    finally:
        executor.close()


@pytest.mark.parametrize("v3_first", [False, True])
def test_same_candidate_cannot_be_republished_under_another_version(tmp_path: Path, v3_first: bool) -> None:
    v1 = write_fixture_request()
    v3 = remember_fixture_request("ExampleAlpha 예시기록")
    assert v1["idempotency_key"] == v3["idempotency_key"]
    first, second = (v3, v1) if v3_first else (v1, v3)
    root = tmp_path / "requests"
    _ = accept_memory_write_request(tmp_path / "vault", root, first, NOW)
    before = {path.name: path.read_bytes() for path in (root / "pending").iterdir()}
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_REPLAY_CONFLICT"):
        _ = accept_memory_write_request(tmp_path / "vault", root, second, NOW)
    assert {path.name: path.read_bytes() for path in (root / "pending").iterdir()} == before
    store = RequestStore(root)
    try:
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("content", ["", " \n\t\r", "bad\x00text", "bad\x7ftext", "\n".join(["x"] * 65),
                                    "[^" * 1_365, "결" * 1_366, "e\u0301", chr(0xD800), chr(0xDFFF)])
def test_new_body_policy_rejects_unusable_or_changed_unicode(content: str) -> None:
    with pytest.raises(ValueError, match="WRITE_REQUEST_INVALID"):
        _ = plain_text_body(content)


@pytest.mark.parametrize("content", ["\n".join(["x"] * 65), "[^" * 1_365, "bad\x00text"])
def test_rejected_v3_does_not_create_a_request_journal(tmp_path: Path, content: str) -> None:
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INVALID"):
        _ = accept_memory_write_request(tmp_path / "vault", tmp_path / "requests", remember_fixture_request(content), NOW)
    assert list(tmp_path.iterdir()) == []


class StopAfterPublication:
    def reach(self, event: BarrierEvent) -> None:
        if event.barrier_id.value == "pending_publish_fsync":
            raise RuntimeError("synthetic publication interruption")


@pytest.mark.parametrize("version", [1, 3])
@pytest.mark.parametrize("two_links", [False, True])
def test_orphan_publication_keeps_original_time_after_later_retry(tmp_path: Path, version: int, two_links: bool) -> None:
    config = executor_config(tmp_path)
    request = write_fixture_request() if version == 1 else remember_fixture_request()
    with pytest.raises(RuntimeError, match="synthetic publication interruption"):
        _ = accept_memory_write_request(config.share_root / "vault", config.request_root, request, NOW,
                                        barrier_sink=StopAfterPublication())
    file = next((config.request_root / "pending").glob("*.json"))
    original = file.read_bytes()
    envelope = parse_remember_envelope(original)
    if two_links:
        # Model termination between the final link and unlink of its exact temp.
        os.link(file, file.with_name(f".{file.name}.123.{'a' * 32}.tmp"))
    later = NOW + timedelta(minutes=2)
    accepted = accept_memory_write_request(config.share_root / "vault", config.request_root, request, later)
    assert file.read_bytes() == original
    assert accepted.accepted_at == envelope.accepted_at
    assert file.stat().st_nlink == 1
    assert not tuple(file.parent.glob("*.tmp"))
    executor = RequestExecutor(config)
    try:
        status = executor.store.get(str(accepted.request_id))
        assert status is not None and status.accepted_at == envelope.accepted_at
        result = executor.apply_once(now=later)
        assert result.state == "proved", result
        assert executor.apply_once(now=later).state == "idle"
    finally:
        executor.close()


@pytest.mark.parametrize("version", [1, 3])
def test_changed_acceptance_envelope_cannot_be_materialized(tmp_path: Path, version: int) -> None:
    config = executor_config(tmp_path)
    request = write_fixture_request() if version == 1 else remember_fixture_request()
    accepted = accept_memory_write_request(config.share_root / "vault", config.request_root, request, NOW)
    file = next((config.request_root / "pending").glob("*.json"))
    original = parse_remember_envelope(file.read_bytes())
    altered = replace(original, accepted_at=(NOW + timedelta(seconds=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    _ = file.write_bytes(canonical_bytes(asdict(altered)) + b"\n")
    executor = RequestExecutor(config)
    try:
        result = executor.apply_once(now=NOW + timedelta(seconds=2))
        assert result.state == "failed" and result.code == "REQUEST_ENVELOPE_MISMATCH", result
        assert executor.store.get(str(accepted.request_id)) is not None
        assert not tuple(config.state_root.glob("**/wiki/memory-*.md"))
    finally:
        executor.close()
