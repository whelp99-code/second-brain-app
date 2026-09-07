from __future__ import annotations

from pathlib import Path

import pytest

from sb.restore import RestoreError
from tests.task30_restore_factory import OLD, restore_fixture


def test_restore_accepts_exact_chain_prefix_and_never_activates(tmp_path: Path) -> None:
    # Given: an old exact-prefix archive and a signed fence at the current chain root.
    fixture = restore_fixture(tmp_path)

    # When: the provider sanitizes the archive through the global mutation service.
    generation, proof = fixture.sanitizer.sanitize(
        fixture.request,
        fixture.executor.mutations,
    )

    # Then: blocked bytes are absent, unrelated bytes survive, and active never changes.
    managed = b"".join(path.read_bytes() for path in generation.root.rglob("*") if path.is_file())
    assert OLD.encode() not in managed
    assert fixture.unrelated in managed
    assert proof.blocked_matches == 0 and proof.scan_errors == 0
    assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
    fixture.executor.close()


def test_restore_rejects_arbitrary_lower_root(tmp_path: Path) -> None:
    # Given: a valid archive whose claimed genesis root is changed to an arbitrary lower root.
    fixture = restore_fixture(tmp_path)
    forged_manifest = fixture.request.archive_manifest.model_copy(
        update={"source_tombstone_set_root": "sha256:" + "f" * 64}
    )
    forged = fixture.request.model_copy(update={"archive_manifest": forged_manifest})

    # When / Then: exact-prefix validation rejects it before creating a restore generation.
    before = {
        path.name
        for path in fixture.executor.generations.generations.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    with pytest.raises(RestoreError, match="TOMBSTONE_SET_STALE"):
        _ = fixture.sanitizer.sanitize(forged, fixture.executor.mutations)
    after = {
        path.name
        for path in fixture.executor.generations.generations.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert after == before
    fixture.executor.close()
