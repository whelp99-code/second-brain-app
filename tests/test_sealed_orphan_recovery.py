"""Rebuilt effects must not strand their obsolete sealed sibling generations."""
import os
from pathlib import Path
from typing import cast

import pytest

from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import GenerationReaderDrainError
from sb.readiness_checks import ReadinessPolicy, generation_checks
from tests.test_generation_cleanup import NOW, config_for
from tests.test_generations import assert_drain_log


@pytest.mark.parametrize("interrupted", [False, True])
def test_maintenance_disposes_only_obsolete_sealed_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    try:
        _ = service.remember("base", "base", NOW)
        abandoned = service.mutate(GenerationMutation("abandoned", GenerationOperation.EFFECT,
            NOW, GenerationAuthority(None, None, activate=False),
            lambda root: (root / "log.md").write_text("obsolete sealed effect\n"))).generation
        # A sealed child of the current generation is still replayable.
        _ = service.maintain(NOW)
        assert abandoned.root.exists()
        _ = service.remember("successor", "successor", NOW)
        current = service.store.active()
        assert abandoned.root.exists()
        if interrupted:
            import os
            replace = os.replace
            def fail_after_move(source: str | Path, target: str | Path) -> None:
                replace(source, target)
                if source == abandoned.root:
                    raise RuntimeError("injected after retirement")
            with monkeypatch.context() as context:
                context.setattr(os, "replace", fail_after_move)
                with pytest.raises(RuntimeError, match="injected after retirement"):
                    _ = service.maintain(NOW)
        _ = service.maintain(NOW)
        assert service.store.active().generation_id == current.generation_id
        assert not abandoned.root.exists()
        assert not any(service.store.staging.iterdir())
        row = cast(tuple[str, str], service.store.journal.execute(
            "SELECT phase,disposal_digest FROM activations WHERE generation_id=?",
            (abandoned.generation_id,)).fetchone())
        assert row[0] == "proved" and row[1].startswith("sha256:")
        assert generation_checks(Path(service.store.state_root) / "generation-journal.db",
                                 NOW, ReadinessPolicy())["generation_cleanup"]
    finally:
        service.close()


def test_obsolete_sealed_descriptor_denial_reports_same_observation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    descriptor: int | None = None
    try:
        _ = service.remember("base", "base", NOW)
        abandoned = service.mutate(GenerationMutation(
            "abandoned", GenerationOperation.EFFECT, NOW,
            GenerationAuthority(None, None, activate=False),
            lambda root: (root / "log.md").write_text("FORBIDDEN_SEALED_CONTENT\n"),
        )).generation
        _ = service.remember("successor", "successor", NOW)
        current = service.store.active()
        descriptor = os.open(abandoned.root, os.O_RDONLY | os.O_DIRECTORY)
        with pytest.raises(GenerationReaderDrainError) as caught:
            _ = service.maintain(NOW)
        assert_drain_log(caplog, caught.value)
        assert caught.value.diagnostics["phase"] == "obsolete-sealed"
        assert caught.value.diagnostics["generation_id"] == abandoned.generation_id
        assert caught.value.diagnostics["readers_status"] == "not-checked"
        assert caught.value.diagnostics["descriptors"] == [{
            "pid": os.getpid(), "fd": descriptor, "path": str(abandoned.root.resolve()),
            "path_status": "observed-at-decision", "source": "/proc/self/fd",
        }]
        assert "FORBIDDEN_SEALED_CONTENT" not in caplog.text
        assert abandoned.root.exists()
        assert service.store.active().generation_id == current.generation_id
        os.close(descriptor)
        descriptor = None
        _ = service.maintain(NOW)
        assert not abandoned.root.exists()
    finally:
        if descriptor is not None:
            os.close(descriptor)
        service.close()
