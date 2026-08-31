from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sb.generations import GenerationStore
from sb.restore import GenerationRestoreSanitizer


def test_restore_rebuilds_distinct_sanitized_generation(tmp_path: Path) -> None:
    old = b"pre-tombstone-value"
    source = tmp_path / "backup"
    (source / "wiki").mkdir(parents=True)
    _ = (source / "wiki/old.md").write_bytes(old)
    _ = (source / "wiki/unrelated.md").write_text("keep", encoding="utf-8")
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation, proof = GenerationRestoreSanitizer(tmp_path / "restore").sanitize(
        archive=source,
        store=store,
        source_high_water=(0, "sha256:" + "0" * 64),
        current_high_water=(1, "sha256:" + "1" * 64),
        forbidden_needles=(old,),
        now=datetime(2026, 8, 31, tzinfo=UTC),
        request_id="restore:1",
    )
    assert proof.sentinel_matches == 0 and proof.scan_errors == 0
    assert not (generation.root / "wiki/old.md").exists()
    assert (generation.root / "wiki/unrelated.md").read_text() == "keep"
    store.close()
