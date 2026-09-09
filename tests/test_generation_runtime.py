from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import final

from pytest import MonkeyPatch

from sb.config import Config
from sb.contracts import SourceRef
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.erasure import ReingressGate
from sb.pipeline import StageReport, run_compile, run_ingest
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _config(tmp_path: Path) -> tuple[Config, Path]:
    share = tmp_path / "share"
    root = share / "vault"
    _ = init_vault(root)
    return (
        Config(
            raw={
                "vault_root": str(root),
                "request_root": str(tmp_path / "requests"),
                "state_root": str(tmp_path / "state"),
                "share_root": str(share),
                "provider_instance_id": "provider:fixture",
                "provider_release_sha": "a" * 40,
            }
        ),
        root,
    )


def test_compile_mutates_a_successor_instead_of_the_active_vault(tmp_path: Path) -> None:
    # Given: a legacy active vault and a stage that records its writable root.
    config, active = _config(tmp_path)
    stage_roots: list[Path] = []

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        stage_roots.append(vault.root)
        return StageReport((), 0, 0, 0, False)

    # When: the normal compile writer runs.
    outcome = run_compile(config, compiler=stage)

    # Then: it writes a successor under the provider generation authority.
    assert outcome.exit_code == 0
    assert active.is_symlink()
    assert len(stage_roots) == 1
    assert stage_roots[0] != active
    assert stage_roots[0].is_relative_to(Path(config.share_root) / "vault-generations" / ".staging")


def test_erasure_rejection_is_a_zero_write_ingress_barrier(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a connector item whose stable source identity is permanently blocked.
    config, active = _config(tmp_path)
    raw = deepcopy(frozen_correction_vector()["request"])
    request = MemoryEffectWriteRequestV2.model_validate(raw)
    gate = ReingressGate(Path(config.state_root) / "reingress.db")
    gate.block_request(request, NOW)
    gate.close()
    blocked_source = request.targets[0].source_identity_full

    @final
    class BlockedAdapter:
        source_id: str = blocked_source

        def scan(
            self,
            cursor: str | None,
        ) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            assert cursor is None
            yield SourceRef(blocked_source, "blocked.md", "v1"), b"blocked-version", {}

        def next_cursor(self) -> str:
            return "after-blocked"

    def adapters(_config: Config) -> dict[str, BlockedAdapter]:
        return {"blocked": BlockedAdapter()}

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)

    # When: ingest encounters the blocked source.
    outcome = run_ingest(config, None)

    # Then: no source, CAS, unit, cursor, inbox, or generation content write follows the error.
    assert outcome.exit_code == 0
    ledger = sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True)
    try:
        assert ledger.execute("SELECT COUNT(*) FROM source_item").fetchone() == (0,)
        assert ledger.execute(
            "SELECT position FROM cursor WHERE source_id=?", (blocked_source,)
        ).fetchone() is None
    finally:
        ledger.close()
    assert not tuple(path for path in active.joinpath("raw").rglob("*") if path.is_file())
    assert not tuple(active.joinpath("inbox").glob("*.md"))


def test_generated_page_updates_across_generations_without_becoming_a_proposal(tmp_path: Path) -> None:
    import hashlib

    from sb.contracts import PageSpec, SourceCite

    config, active = _config(tmp_path)
    payload = b'original source'
    digest = hashlib.sha256(payload).hexdigest()
    page = PageSpec('updating', 'Updating', f'first [^{digest[:8]}]',
                    [SourceCite(digest[:8], 'inbox:updating.md', digest)], 'active')

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        target = vault.root / 'raw' / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_bytes(payload)
        return StageReport((page,), 0, 0, 1, False)

    first = run_compile(config, compiler=stage)
    assert first.exit_code == 0
    first_generation = active.resolve()
    first_digest = 'sha256:' + hashlib.sha256((active / 'wiki/updating.md').read_bytes()).hexdigest()
    page = PageSpec('updating', 'Updating', f'second [^{digest[:8]}]', page.sources, 'active')
    second = run_compile(config, compiler=stage)
    assert second.exit_code == 0 and active.resolve() != first_generation
    assert 'second' in (active / 'wiki/updating.md').read_text()
    assert not tuple((active / 'wiki/_proposed').glob('*.md'))
    second_digest = 'sha256:' + hashlib.sha256((active / 'wiki/updating.md').read_bytes()).hexdigest()
    assert first_digest != second_digest
    connection = sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT content_digest,approval_status FROM bound_knowledge WHERE page_id='wiki/updating'").fetchall()
        assert set(rows) == {(first_digest, 'APPROVED'), (second_digest, 'APPROVED')}
    finally:
        connection.close()


def test_repeated_proposals_never_bless_or_overwrite_a_human_edit(tmp_path: Path) -> None:
    import hashlib

    from sb.contracts import PageSpec, SourceCite
    from sb.generation_runtime import GenerationMutationService
    from sb.generation_runtime_models import (
        GenerationAuthority,
        GenerationMutation,
        GenerationOperation,
    )

    config, active = _config(tmp_path)
    payload = b'human edit evidence'
    digest = hashlib.sha256(payload).hexdigest()
    page = PageSpec('protected', 'Protected', f'generated [^{digest[:8]}]',
                    [SourceCite(digest[:8], 'inbox:protected.md', digest)], 'active')

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        target = vault.root / 'raw' / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_bytes(payload)
        return StageReport((page,), 0, 0, 1, False)

    assert run_compile(config, compiler=stage).exit_code == 0
    marker = active / '.sb/compiled/protected.sha'
    expected_marker = marker.read_bytes()
    service = GenerationMutationService.from_config(config)
    try:
        def human_edit(root: Path) -> None:
            # Simulate an operator edit without changing the last generated hash.
            path = root / 'wiki/protected.md'
            _ = path.write_text(path.read_text().replace('generated', 'human-edited'))

        _ = service.mutate(GenerationMutation('test:human-edit', GenerationOperation.RUN, NOW,
                                             GenerationAuthority(None, None), human_edit))
    finally:
        service.close()
    for replacement in ('next-one', 'next-two'):
        page = PageSpec('protected', 'Protected', f'{replacement} [^{digest[:8]}]', page.sources, 'active')
        outcome = run_compile(config, compiler=stage)
        assert outcome.exit_code == 1 and outcome.status == 'failed'
        assert 'human-edited' in (active / 'wiki/protected.md').read_text()
        assert replacement in (active / 'wiki/_proposed/protected.md').read_text()
        assert marker.read_bytes() == expected_marker
        connection = sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT page_id,content_digest FROM bound_knowledge").fetchall()
            assert rows == [('wiki/protected', 'sha256:' + expected_marker.decode().strip())]
        finally:
            connection.close()


def test_invalid_compiled_marker_cannot_replace_active_generation(tmp_path: Path) -> None:
    import pytest

    from sb.generation_runtime_models import GenerationMutationError

    for kind in ('symlink', 'hardlink', 'directory', 'malformed'):
        case = tmp_path / kind
        config, active = _config(case)
        with Ledger(active):
            pass
        outside = case / 'outside.sha'
        _ = outside.write_text('a' * 64)
        compiled = active / '.sb/compiled'
        compiled.mkdir(parents=True)
        marker = compiled / 'page.sha'
        if kind == 'symlink':
            marker.symlink_to(outside)
        elif kind == 'hardlink':
            marker.hardlink_to(outside)
        elif kind == 'directory':
            marker.mkdir()
        else:
            _ = marker.write_text('not-a-digest')

        def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
            del ledger, vault, run_id
            raise AssertionError('unsafe marker must be rejected before mutation')

        with pytest.raises(GenerationMutationError, match='GENERATION_SOURCE_UNSAFE'):
            _ = run_compile(config, compiler=stage)
        assert active.is_dir() and not active.is_symlink()
        assert outside.read_text() == 'a' * 64


def test_failed_page_write_never_registers_knowledge(tmp_path: Path) -> None:
    from sb.contracts import PageSpec, SourceCite

    config, active = _config(tmp_path)

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((PageSpec('invalid', 'Invalid', 'missing source [^aaaaaaaa]', [SourceCite('aaaaaaaa', 'inbox:missing', 'a' * 64)], 'active'),), 0, 0, 1, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 1
    assert not (active / 'wiki/invalid.md').exists()
    connection = sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True)
    try:
        assert connection.execute('SELECT COUNT(*) FROM bound_knowledge').fetchone() == (0,)
    finally:
        connection.close()
