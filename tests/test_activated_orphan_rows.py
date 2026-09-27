"""Non-current activated journal rows are not proved by a later remember."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.ops import doctor

NOW = datetime(2026, 9, 10, tzinfo=UTC)
ORPHAN = "sbgen:v1:" + "ab" * 32


def config(tmp_path: Path) -> Config:
    share = tmp_path / "share"
    return Config(
        raw={
            "vault_root": str(share / "vault"),
            "share_root": str(share),
            "state_root": str(tmp_path / "state"),
            "request_root": str(tmp_path / "requests"),
            "provider_instance_id": "provider:fixture",
            "provider_release_sha": "a" * 40,
            "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "deny"}],
        }
    )


_config = config


def test_remember_does_not_prove_non_current_activated_orphans(tmp_path: Path) -> None:
    mutations = GenerationMutationService.from_config(_config(tmp_path))
    try:
        _ = mutations.remember("first", "one", NOW)
        _ = mutations.remember("second", "two", NOW)
        _ = mutations.store.journal.execute(
            """
            INSERT INTO activations(
              generation_id, parent_generation_id, phase, manifest_digest,
              pointer_target, created_at, updated_at
            ) VALUES (?, NULL, 'activated', 'sha256:' || ?, NULL, ?, ?)
            """,
            (ORPHAN, "c" * 64, NOW.isoformat(), NOW.isoformat()),
        )
        mutations.store.journal.commit()
        _ = mutations.remember("third", "three", NOW)
        phase = TypeAdapter[tuple[str] | None](tuple[str] | None).validate_python(mutations.store.journal.execute(
            "SELECT phase FROM activations WHERE generation_id=?",
            (ORPHAN,),
        ).fetchone())
        current = TypeAdapter[tuple[str] | None](tuple[str] | None).validate_python(mutations.store.journal.execute(
            "SELECT phase FROM activations WHERE generation_id=?",
            (mutations.store.active().generation_id,),
        ).fetchone())
    finally:
        mutations.close()
    assert phase is not None
    assert phase[0] == "activated"
    assert current is not None
    assert current[0] == "proved"


def test_doctor_warns_on_non_current_activated_orphans(tmp_path: Path) -> None:
    config = _config(tmp_path)
    mutations = GenerationMutationService.from_config(config)
    try:
        _ = mutations.remember("first", "one", NOW)
        _ = mutations.remember("second", "two", NOW)
        _ = mutations.store.journal.execute(
            """
            INSERT INTO activations(
              generation_id, parent_generation_id, phase, manifest_digest,
              pointer_target, created_at, updated_at
            ) VALUES (?, NULL, 'activated', 'sha256:' || ?, NULL, ?, ?)
            """,
            (ORPHAN, "c" * 64, NOW.isoformat(), NOW.isoformat()),
        )
    finally:
        mutations.close()
    checks = {check.name: check for check in doctor(config)}
    assert checks["activation-orphans"].status == "warn"
    assert checks["activation-orphans"].detail == "count=1"


def test_doctor_passes_without_activated_orphans(tmp_path: Path) -> None:
    config = _config(tmp_path)
    mutations = GenerationMutationService.from_config(config)
    try:
        _ = mutations.remember("first", "one", NOW)
        _ = mutations.remember("second", "two", NOW)
    finally:
        mutations.close()
    checks = {check.name: check for check in doctor(config)}
    assert checks["activation-orphans"].status == "pass"
    assert checks["activation-orphans"].detail == "none"
