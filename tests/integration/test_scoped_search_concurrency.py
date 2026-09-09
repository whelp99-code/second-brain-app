"""Real independent writer overlaps a pinned, classified search without sleeps."""
from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.remember_page import materialize_remember
from sb.scoped_search import search_scoped_records
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1
from tests.fixtures.generation_concurrency import ControlPipe

NOW = datetime(2026, 9, 10, tzinfo=UTC)
SCOPE = SourceAccess("principal:owner", ("project:allowed",), "1")


def _config(root: Path) -> Config:
    return Config(raw={"vault_root": str(root / "share/vault"), "share_root": str(root / "share"),
        "state_root": str(root / "state"), "request_root": str(root / "requests"),
        "export_root": str(root / "exports"), "knowledge_registry": str(root / "registry.db")})


def _write(root: Path, number: int, allowed: bool) -> None:
    materialize_remember(root, content=f"SharedProbe {'permitted' if allowed else 'forbidden'} {number}",
        candidate_id="memcand:pos:v1:" + f"{number:064x}", created_at=NOW.isoformat(), release_sha="a" * 40,
        source_access=SCOPE if allowed else SourceAccess("principal:owner", ("project:denied",), "1"))


def _successor(root: str, control: ControlPipe) -> None:
    service = GenerationMutationService.from_config(_config(Path(root)))
    try:
        def apply(folder: Path) -> None:
            _write(folder, 100, True)
            control.send("preparing")
            if control.recv() != "continue":
                raise RuntimeError("invalid fixture command")
        result = service.mutate(GenerationMutation("search:successor", GenerationOperation.REMEMBER,
            NOW, GenerationAuthority(None, None), apply))
        control.send(result.generation.generation_id)
    finally:
        service.close()
        control.close()


def test_scoped_search_keeps_pinned_results_until_independent_writer_switches(tmp_path: Path):
    service = GenerationMutationService.from_config(_config(tmp_path))
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_successor, args=(str(tmp_path), child))

    def search(generation, query="SharedProbe"):
        manifest = generation.manifest
        identity = GenerationIdentityV1(manifest.provider_instance_id, generation.generation_id,
            manifest.generation_digest, generation.head, generation.tree)
        return search_scoped_records(generation.root, identity, SCOPE, query, 10)

    try:
        def seed(folder: Path) -> None:
            for number in range(10):
                _write(folder, number, number == 9)
        original = service.mutate(GenerationMutation("search:seed", GenerationOperation.REMEMBER,
            NOW, GenerationAuthority(None, None), seed)).generation
        baseline = search(original)
        assert len(baseline) == 1 and "permitted" in str(baseline)
        process.start()
        child.close()
        assert parent.poll(20), "writer did not reach preparation"
        assert parent.recv() == "preparing"
        with service.store.pin("scoped-concurrency", NOW) as pin:
            assert pin.generation.generation_id == original.generation_id
            parent.send("continue")
            # The writer cannot activate or retire the parent while this pin is
            # held. Search overlaps a real in-flight successor, not a fake index.
            assert search(pin.generation) == baseline
            assert search(pin.generation, "forbidden") == []
            assert service.store.active().generation_id == original.generation_id
            assert original.root.exists()
        assert parent.poll(20), "writer did not finish after reader released its pin"
        successor_id = parent.recv()
        process.join(10)
        assert process.exitcode == 0
        with service.store.pin("scoped-fresh-reader", NOW) as pin:
            assert pin.generation.generation_id == successor_id != original.generation_id
            fresh = search(pin.generation)
            assert len(fresh) == 2
            assert baseline[0] in fresh
            assert any("100" in str(row["record"]) for row in fresh)
            assert search(pin.generation, "forbidden") == []
        assert not original.root.exists()
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(10)
            process.close()
        parent.close()
        child.close()
        service.close()
