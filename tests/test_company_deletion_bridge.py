"""Bridge registered original deletion facts without adding a deletion API."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_db_freshness_models import FreshnessRegistry, RegistryDeletionSource
from sb.company_freshness_deletion import DeletionFact
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.test_company_db_freshness import (
    PROVIDER_SCOPE,
    RECEIPT_BINDING,
    freshness_read,
    provider_at,
)


def test_registered_deletion_records_original_times_then_closes_unsafe_enrollment(
    tmp_path: Path,
) -> None:
    provider = provider_at(tmp_path)
    before = provider.read_freshness(freshness_read(provider)).checkpoint
    assert before is not None
    intent = DeletionFact(
        schema_version=1,
        scope=PROVIDER_SCOPE,
        authority_id="existing-approved-deleter",
        source_record_id="deletion-original:intent",
        deletion_plan_digest=RECEIPT_BINDING,
        authorization_receipt_digest="sha256:" + "33" * 32,
        source_fence=7,
        source_root="sha256:" + "44" * 32,
        original_at="2026-10-15T00:00:00.000Z",
        stage="intent",
    )
    completed = intent.model_copy(
        update={
            "source_record_id": "deletion-original:complete",
            "stage": "deleted",
            "original_at": "2026-10-15T00:01:00.000Z",
        }
    )
    paths: list[Path] = []
    digests: list[str] = []
    for name, fact in (("intent.json", intent), ("completed.json", completed)):
        path = tmp_path / name
        payload = canonical_bytes(model_object(fact))
        _ = path.write_bytes(payload)
        path.chmod(0o600)
        paths.append(path)
        digests.append("sha256:" + hashlib.sha256(payload).hexdigest())
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    registry = registry.model_copy(
        update={
            "deletion_sources": [
                RegistryDeletionSource(
                    scope=PROVIDER_SCOPE,
                    authority_id=intent.authority_id,
                    deletion_plan_digest=RECEIPT_BINDING,
                    intent_path=str(paths[0]),
                    intent_digest=digests[0],
                    completion_path=str(paths[1]),
                    completion_digest=digests[1],
                )
            ]
        }
    )
    _ = provider.registry_path.write_bytes(canonical_bytes(model_object(registry)))
    before_database = provider.database.read_bytes()
    spool = provider.witness_dir / "frames.jsonl"
    before_spool = spool.read_bytes()
    result = provider.bridge_deletion(
        scope=PROVIDER_SCOPE,
        deletion_plan_digest=RECEIPT_BINDING,
        expected_checkpoint=before,
        challenge="deletion:original",
    )
    assert result.outcome == "recorded"
    assert result.checkpoint is not None
    assert result.checkpoint.stores.second_brain.deletion_sequence == 2
    with closing(sqlite3.connect(provider.database)) as db:
        evidence: list[tuple[str, str]] = db.execute(
            """SELECT source_record_id,json_extract(evidence_json,'$.metadata.original_at')
            FROM company_freshness_evidence WHERE stream='deletion' ORDER BY sequence""",
        ).fetchall()
        operations: list[tuple[str]] = db.execute(
            "SELECT state FROM company_freshness_operations",
        ).fetchall()
        candidate_tables: list[tuple[str]] = db.execute(
            "SELECT name FROM sqlite_master WHERE name='company_memory_candidates'",
        ).fetchall()
    assert operations == [("finished",)]
    assert candidate_tables == []
    assert evidence == [
        ("deletion-original:intent:intent", intent.original_at),
        ("deletion-original:complete:complete", completed.original_at),
    ]
    assert (
        provider.read_freshness(
            freshness_read(provider).model_copy(update={"observed_checkpoint": result.checkpoint}),
        ).status
        == "mismatch"
    )
    surviving_anchor = provider.anchor.read_value()
    _ = provider.database.write_bytes(before_database)
    _ = spool.write_bytes(before_spool)
    replay = provider.bridge_deletion(
        scope=PROVIDER_SCOPE,
        deletion_plan_digest=RECEIPT_BINDING,
        expected_checkpoint=before,
        challenge="deletion:restored",
    )
    assert replay.outcome == "error"
    assert provider.anchor.read_value() == surviving_anchor
    assert provider.database.read_bytes() == before_database


def test_unregistered_deletion_cannot_reserve(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    before = provider.read_freshness(freshness_read(provider)).checkpoint
    assert before is not None
    nv = provider.anchor.read_value()
    result = provider.bridge_deletion(
        scope=PROVIDER_SCOPE,
        deletion_plan_digest=RECEIPT_BINDING,
        expected_checkpoint=before,
        challenge="deletion:forged",
    )
    assert result.outcome == "error"
    assert provider.anchor.read_value() == nv
