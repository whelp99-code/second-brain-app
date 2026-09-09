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


@pytest.mark.parametrize("change", ["shift", "copy", "move"])
def test_restore_shifted_deleted_record_cannot_survive_signed_restore(
    tmp_path: Path, change: str,
) -> None:
    from datetime import datetime

    from sb.restore_models import RestoreArchiveSource, build_restore_archive_manifest

    fixture = restore_fixture(tmp_path)
    try:
        archive = fixture.request.archive
        for path in tuple(archive.rglob('*.md')):
            if OLD.encode() in path.read_bytes():
                if change == "shift":
                    path.write_bytes(b'New introduction\n' + path.read_bytes())
                else:
                    copied = archive / 'wiki' / 'relocated.md'
                    copied.write_bytes(b'New introduction\n' + path.read_bytes())
                    copied.chmod(0o600)
                    if change == "move":
                        path.unlink()
        old = fixture.request.archive_manifest
        manifest = build_restore_archive_manifest(archive, RestoreArchiveSource(
            provider_instance_id=old.provider_instance_id,
            source_generation_id=old.source_generation_id,
            source_generation_manifest_digest=old.source_generation_manifest_digest,
            source_tombstone_sequence=old.source_tombstone_sequence,
            source_tombstone_set_root=old.source_tombstone_set_root,
            created_at=datetime.fromisoformat(old.created_at),
        ))
        request = fixture.request.model_copy(update={'archive_manifest': manifest})
        generation, proof = fixture.sanitizer.sanitize(request, fixture.executor.mutations)
        managed = b''.join(p.read_bytes() for p in generation.root.rglob('*') if p.is_file())
        assert OLD.encode() not in managed
        assert fixture.unrelated in managed
        assert proof.blocked_matches == 0
        assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
    finally:
        fixture.executor.close()


@pytest.mark.parametrize("invalid_manifest", [False, True])
def test_managed_restore_preserves_existing_request_staging(
    tmp_path: Path, invalid_manifest: bool,
) -> None:
    import hashlib

    fixture = restore_fixture(tmp_path)
    try:
        request_key = hashlib.sha256(fixture.request.request_id.encode()).hexdigest()
        previous = fixture.sanitizer.workspace / f'restore-{request_key}'
        previous.mkdir()
        evidence = previous / 'recovery-evidence.txt'
        evidence.write_text('other interrupted restore')
        if invalid_manifest:
            (fixture.request.archive / 'wiki' / 'unexpected.md').write_text('extra bytes')
            with pytest.raises(RestoreError, match="RESTORE_ARCHIVE_INVALID"):
                fixture.sanitizer.sanitize(fixture.request, fixture.executor.mutations)
        else:
            _, proof = fixture.sanitizer.sanitize(fixture.request, fixture.executor.mutations)
            assert proof.scan_errors == 0
        assert evidence.read_text() == 'other interrupted restore'
        assert list(fixture.sanitizer.workspace.iterdir()) == [previous]
    finally:
        fixture.executor.close()
