from __future__ import annotations

import inspect
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.restore import GenerationRestoreSanitizer


def test_restore_api_has_no_caller_roots_needles_or_activation_flag() -> None:
    # Given: the provider restore sanitizer public boundary.
    parameters = inspect.signature(GenerationRestoreSanitizer.sanitize).parameters

    # When: its authority-bearing inputs are inventoried.
    forbidden = {"source_high_water", "current_high_water", "forbidden_needles", "activate"}

    # Then: callers cannot select roots, byte needles, or activation.
    assert forbidden.isdisjoint(parameters)
    assert {"request", "mutations"} <= set(parameters)


def test_restore_workspace_is_private(tmp_path: Path) -> None:
    # Given / When: a restore sanitizer owns an isolated workspace.
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    sanitizer = GenerationRestoreSanitizer(
        tmp_path / "restore",
        "provider:fixture",
        {"jarvis:fixture": key.public_key()},
    )

    # Then: the workspace is provider-private.
    assert sanitizer.workspace.stat().st_mode & 0o777 == 0o700


def test_source_generation_digest_survives_content_disposal(tmp_path: Path) -> None:
    from tests.task30_restore_factory import restore_fixture

    fixture = restore_fixture(tmp_path)
    try:
        source = fixture.request.archive_manifest
        store = fixture.executor.generations
        row = store.journal.execute(
            'SELECT manifest_digest FROM activations WHERE generation_id=?',
            (source.source_generation_id,)).fetchone()
        assert row == (source.source_generation_manifest_digest,)
        assert store.active().generation_id != source.source_generation_id
        # Disposal removes the original generation folder; the anchor is retained
        # in the operational journal rather than recovered from untrusted archive metadata.
        assert not (store.generations / source.source_generation_id).exists()
        assert store.journal.execute('SELECT manifest_digest FROM activations WHERE generation_id=?',
            ('sbgen:v1:' + 'f' * 64,)).fetchone() is None
    finally:
        fixture.executor.close()
