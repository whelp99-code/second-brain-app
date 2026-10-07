"""H5: maintain sweeps activated rows whose generation directories are gone."""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from pydantic import TypeAdapter

from sb.generation_runtime import GenerationMutationService
from sb.readiness_checks import ReadinessPolicy, generation_checks
from tests.test_activated_orphan_rows import NOW, config


def test_maintain_proves_missing_directory_orphans_and_clears_cleanup(tmp_path: Path) -> None:
    mutations = GenerationMutationService.from_config(config(tmp_path))
    try:
        _ = mutations.remember("keep", "one", NOW)
        current_id = mutations.store.active().generation_id
        stamp = (NOW - timedelta(days=1)).isoformat()
        for suffix in ("aa", "bb", "cc"):
            _ = mutations.store.journal.execute(
                """
                INSERT INTO activations(
                  generation_id, parent_generation_id, phase, manifest_digest,
                  pointer_target, created_at, updated_at
                ) VALUES (?, NULL, 'activated', 'sha256:' || ?, NULL, ?, ?)
                """,
                ("sbgen:v1:" + suffix * 32, "c" * 64, stamp, stamp),
            )
        mutations.store.journal.commit()
        _ = mutations.maintain(NOW)
        conn = sqlite3.connect(tmp_path / "state" / "generation-journal.db")
        rows = TypeAdapter(list[tuple[str, str, str | None]]).validate_python(conn.execute(
            "SELECT generation_id,phase,disposal_digest FROM activations",
        ).fetchall(), strict=True)
        conn.close()
        current_row = next(row for row in rows if row[0] == current_id)
        orphans = [row for row in rows if row[0] != current_id]
        assert current_row[1] in {"activated", "proved"}
        assert len(orphans) == 3
        assert {row[1] for row in orphans} == {"proved"}
        assert all(isinstance(row[2], str) and row[2].startswith("sha256:") for row in orphans)
        journal = tmp_path / "state" / "generation-journal.db"
        assert generation_checks(journal, NOW, ReadinessPolicy())["generation_cleanup"] is True
    finally:
        mutations.close()


def test_sweep_skips_generation_with_existing_directory(tmp_path: Path) -> None:
    mutations = GenerationMutationService.from_config(config(tmp_path))
    try:
        _ = mutations.remember("keep", "one", NOW)
        current_id = mutations.store.active().generation_id
        live = "sbgen:v1:" + "dd" * 32
        (tmp_path / "share" / "vault-generations" / live).mkdir(parents=True)
        stamp = (NOW - timedelta(days=1)).isoformat()
        _ = mutations.store.journal.execute(
            """
            INSERT INTO activations(
              generation_id, parent_generation_id, phase, manifest_digest,
              pointer_target, created_at, updated_at
            ) VALUES (?, NULL, 'activated', 'sha256:' || ?, NULL, ?, ?)
            """,
            (live, "c" * 64, stamp, stamp),
        )
        mutations.store.journal.commit()
        _ = mutations.maintain(NOW)
        conn = sqlite3.connect(tmp_path / "state" / "generation-journal.db")
        phase = TypeAdapter[tuple[str] | None](tuple[str] | None).validate_python(conn.execute(
            "SELECT phase FROM activations WHERE generation_id=?", (live,),
        ).fetchone(), strict=True)
        kept = TypeAdapter[tuple[str] | None](tuple[str] | None).validate_python(conn.execute(
            "SELECT generation_id FROM activations WHERE generation_id=?",
            (current_id,),
        ).fetchone(), strict=True)
        conn.close()
        assert phase == ("activated",)
        assert kept is not None
    finally:
        mutations.close()
