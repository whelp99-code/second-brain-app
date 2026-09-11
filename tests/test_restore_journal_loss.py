"""Journal-less DR stays denied. Product write happens on a restored generation."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import GenerationStore
from sb.remember_page import materialize_remember
from sb.restore_source import RestoreSourceError, verified_restore_source
from sb.source_access import SourceAccess
from tests.task30_restore_factory import restore_fixture
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


def test_restore_fixture_then_product_write_on_same_generation(tmp_path: Path) -> None:
    backup_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    restored = restore_fixture(tmp_path, full_source=True)
    generation, proof = restored.sanitizer.sanitize(restored.request, restored.executor.mutations)
    assert proof.blocked_matches == 0
    needle = "post-restore-fixture-needle"
    now = datetime.now(UTC)

    def write(folder: Path) -> None:
        materialize_remember(
            folder, content=needle, candidate_id="memcand:pos:v1:" + "d" * 64,
            created_at=now.isoformat(), release_sha=restored.executor.config.provider_release_sha,
            source_access=SourceAccess("principal:owner", ("project:a",), "policy:1"),
        )

    written = restored.executor.mutations.mutate(GenerationMutation(
        "m12:post-restore", GenerationOperation.REMEMBER, now, GenerationAuthority(None, None), write,
    ))
    pages = [path.relative_to(written.generation.root).as_posix() for path in written.generation.root.rglob("*.md") if needle in path.read_text(encoding="utf-8")]
    rto_s = round(time.perf_counter() - started, 4)
    evidence = {
        "rpo_backup_at": backup_at,
        "rto_seconds": rto_s,
        "restore_generation": generation.generation_id,
        "write_generation": written.generation.generation_id,
        "blocked_matches": proof.blocked_matches,
        "post_pages": pages,
        "tombstone_sequence": generation.manifest.tombstone_sequence,
        "cutover": False,
    }
    Path("/var/tmp/m12-journal-restore-write.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert pages
