"""Journal-less DR stays denied. Product write is an accepted request on the restored executor."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generations import GenerationStore
from sb.mcp_contract import JsonObject, canonical_bytes, write_fixture_request
from sb.restore_source import RestoreSourceError, verified_restore_source
from sb.stable_requests import accept_stable_v1_request
from tests.task30_restore_factory import NOW, restore_fixture
from tests.test_restore_source import fixture


def test_missing_journal_is_denied(tmp_path: Path) -> None:
    archive, store, manifest = fixture(tmp_path)
    empty = GenerationStore(
        tmp_path / "empty/state", tmp_path / "empty/share",
        provider_instance_id="provider:fixture", provider_release_sha="a" * 40,
    )
    try:
        with pytest.raises(RestoreSourceError, match="RESTORE_SOURCE_ANCHOR_MISSING"):
            verified_restore_source(archive, manifest, empty)
        observed = verified_restore_source(archive, manifest, store)
        digest = observed["generation_digest"]
        assert isinstance(digest, str) and digest.startswith("sha256:")
    finally:
        store.close()
        empty.close()


def _digest(domain: bytes, value: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _remember_request(content: str) -> JsonObject:
    request = write_fixture_request()
    request["candidate_id"] = "memcand:pos:v1:" + "b" * 64
    request["candidate_digest"] = "sha256:" + "c" * 64
    request["classification_digest"] = "sha256:" + "d" * 64
    request["payload"] = {"content": content}
    receipt = request["receipt"]
    assert isinstance(receipt, dict)
    receipt["candidate_id"] = request["candidate_id"]
    receipt["candidate_digest"] = request["candidate_digest"]
    receipt["classification_digest"] = request["classification_digest"]
    request["receipt_digest"] = _digest(b"orca-jarvis/memory-write-receipt/v1\0", receipt)
    identity: JsonObject = {
        "candidate_id": request["candidate_id"],
        "candidate_digest": request["candidate_digest"],
        "classification_digest": request["classification_digest"],
        "operation": "remember",
    }
    request["idempotency_key"] = "memidem:pos:v1:" + _digest(b"orca-jarvis/memory-write-idempotency/v1\0", identity)[7:]
    request.pop("request_id", None)
    request.pop("request_digest", None)
    request_digest = _digest(b"orca-jarvis/memory-write-request/v1\0", request)
    request["request_id"] = "memreq:pos:v1:" + request_digest[7:]
    request["request_digest"] = request_digest
    return request


def test_restore_fixture_then_accepted_request_write(tmp_path: Path) -> None:
    backup_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    restored = restore_fixture(tmp_path, full_source=True)
    generation, proof = restored.sanitizer.sanitize(restored.request, restored.executor.mutations)
    assert proof.blocked_matches == 0
    needle = "post-restore-product-write"
    accepted = accept_stable_v1_request(restored.executor.config.request_root, _remember_request(needle), NOW)
    applied = restored.executor.apply_once(now=NOW)
    active = restored.executor.generations.active()
    pages = [
        path.relative_to(active.root).as_posix()
        for path in active.root.rglob("*.md")
        if needle in path.read_text(encoding="utf-8")
    ]
    rto_s = round(time.perf_counter() - started, 4)
    evidence = {
        "rpo_backup_at": backup_at,
        "rto_seconds": rto_s,
        "restore_generation": generation.generation_id,
        "write_generation": active.generation_id,
        "applied_state": applied.state,
        "accepted_request_id": accepted.request_id,
        "blocked_matches": proof.blocked_matches,
        "post_pages": pages,
        "tombstone_sequence": active.manifest.tombstone_sequence,
        "cutover": False,
    }
    Path("/var/tmp/m12-journal-restore-write.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert applied.state == "proved"
    assert pages
