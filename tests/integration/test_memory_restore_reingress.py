from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sb.generations import GenerationStore
from sb.restore import GenerationRestoreSanitizer


def test_stale_backup_cannot_resurrect_tombstoned_bytes(tmp_path: Path) -> None:
    sentinel = b"forgotten-runtime-record"
    backup = tmp_path / "backup"
    backup.mkdir()
    _ = (backup / "record.md").write_bytes(sentinel)
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation, proof = GenerationRestoreSanitizer(tmp_path / "restore").sanitize(
        archive=backup, store=store,
        source_high_water=(0, "sha256:" + "0" * 64),
        current_high_water=(2, "sha256:" + "2" * 64),
        forbidden_needles=(sentinel,), now=datetime(2026, 8, 31, tzinfo=UTC),
        request_id="restore:stale", activate=False,
    )
    assert proof.sentinel_matches == 0
    assert sentinel not in b"".join(
        path.read_bytes() for path in generation.root.rglob("*") if path.is_file()
    )
    store.close()
