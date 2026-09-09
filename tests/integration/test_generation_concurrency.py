from __future__ import annotations

import fcntl
import multiprocessing
import os
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, tzinfo
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import perf_counter
from typing import Self, cast, override

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import StdioServerParameters
from mcp.client import Client

import sb.mcp as mcp_module
from sb.config import load_config
from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_requests import accept_effect_request
from sb.generation_runtime import GenerationMutationService
from sb.request_executor import RequestExecutor
from tests.fixtures.generation_concurrency import ControlPipe, compile_worker, remember_worker
from tests.task30_effect_factory import effect_request
from tests.task30_process_harness import NOW, executor_config, provider_fixture


def seed(root: Path) -> tuple[Path, str, str]:
    fixture = provider_fixture(root)
    with fixture.config.open("a") as stream:
        _ = stream.write(f'vault_root = "{fixture.share_root / "vault"}"\n')
    executor = RequestExecutor(executor_config(root))
    try:
        assert executor.apply_once(now=NOW).state == "proved"
        generation = executor.generations.active()
        page = next(generation.root.joinpath("wiki").glob("memory-*.md"))
        return fixture.config, generation.generation_id, page.relative_to(generation.root).with_suffix("").as_posix()
    finally:
        executor.close()


def receive(control: ControlPipe) -> dict[str, str | int]:
    assert control.poll(15), "real worker did not reach the expected boundary"
    value = control.recv()
    assert isinstance(value, dict)
    return cast(dict[str, str | int], value)


@contextmanager
def worker(target: Callable[[str, ControlPipe], None], config: Path) -> Generator[
    tuple[BaseProcess, ControlPipe], None, None
]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=target, args=(str(config), child))
    process.start()
    child.close()
    try:
        yield process, parent
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)
        assert not process.is_alive()
        parent.close()
        process.close()


async def read_mcp(config: Path, page: str, expected: str) -> float:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "sb.mcp"],
                                       env={"SB_CONFIG": str(config), "SB_MCP_CONTRACT_PROFILE": "task32-schema4"})
    async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=10) as client:
        started = perf_counter()
        with anyio.fail_after(10):
            for method, arguments in (("sb_search", {"query": "ExampleAlpha", "limit": 1}),
                                      ("sb_read_page", {"id": page}),
                                      ("sb_generation_status", {})):
                result = await client.call_tool(method, arguments)
                assert not result.is_error
                value = cast(object, result.structured_content)
                assert isinstance(value, dict)
                assert value["generation_id"] == expected
                if method == "sb_search":
                    assert value["results"]
                elif method == "sb_read_page":
                    assert value["records"]
        return perf_counter() - started


def test_real_mcp_reads_sealed_parent_while_pipeline_compile_is_paused(tmp_path: Path) -> None:
    config, original, page = seed(tmp_path)
    with worker(compile_worker, config) as (process, control):
        event = receive(control)
        assert event["event"] == "preparing"
        assert "/.staging/" in str(event["root"])
        # The compiler cannot complete until this process releases it. A passing
        # read therefore proves overlap rather than relying on a timing sleep.
        elapsed = anyio.run(read_mcp, config, page, original)
        assert process.is_alive()
        control.send("continue")
        completed = receive(control)
        assert completed["event"] == "completed" and completed["exit_code"] == 0
        assert completed["generation"] != original
        assert not (tmp_path / "share" / "vault-generations" / original).exists()
        print(f"real MCP search+page+status during paused compile: {elapsed:.3f}s")


async def reject_stale_generation(config: Path, page: str, high_water: tuple[int, str]) -> None:
    now = datetime.now(UTC)
    fence = create_read_fence(provider_instance_id="provider:fixture", purpose="memory_read", operation="read",
                              sequence=high_water[0], set_root=high_water[1], issued_at=format_instant(now),
                              not_before=format_instant(now), expires_at=format_instant(now + timedelta(seconds=30)),
                              nonce="concurrent-deletion", signing_key_id="jarvis:fixture",
                              private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))))
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "sb.mcp"],
                                       env={"SB_CONFIG": str(config), "SB_MCP_CONTRACT_PROFILE": "task32-schema4"})
    async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=10) as client:
        with anyio.fail_after(10):
            for arguments, code in (({"id": page}, "TOMBSTONE_FENCE_REQUIRED"),
                                    ({"id": page, "read_fence": fence.model_dump(mode="json")}, "TOMBSTONE_SET_STALE")):
                result = await client.call_tool("sb_read_page", arguments)
                assert result.is_error and code in str(result.content)


def test_second_writer_preserves_first_successor_and_reader_blocks_switch(tmp_path: Path) -> None:
    config, original, _page = seed(tmp_path)
    service = GenerationMutationService.from_config(load_config(config))
    try:
        pending = service.remember("pending before concurrent compile", "prior-pending", NOW).name
        original = service.store.active().generation_id
    finally:
        service.close()
    with worker(compile_worker, config) as (_compiler, first):
        assert receive(first)["event"] == "preparing"
        with worker(remember_worker, config) as (_remember, second):
            assert receive(second)["event"] == "ready"
            service = GenerationMutationService.from_config(load_config(config))
            try:
                with service.store.pin("held-reader", NOW) as pin:
                    assert pin.generation.generation_id == original
                    for name in ("generation-writer.lock", "generation.lock"):
                        fd = os.open(tmp_path / "state" / name, os.O_RDWR)
                        try:
                            with pytest.raises(BlockingIOError):
                                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        finally:
                            os.close(fd)
                    second.send("continue")
                    first.send("continue")
                    assert service.store.active().generation_id == original
                compiled = receive(first)
                remembered = receive(second)
                assert compiled["event"] == remembered["event"] == "completed"
                assert remembered["parent"] == compiled["generation"]
                active = service.store.active()
                assert (active.root / "inbox" / str(remembered["inbox"])).is_file()
                assert (active.root / "inbox" / pending).read_text() == "pending before concurrent compile"
                assert tuple(active.root.joinpath("wiki").glob("memory-*.md"))
                service.remember("later successor", "later", NOW)
                successor = service.store.active()
                assert (successor.root / "inbox" / pending).read_text() == "pending before concurrent compile"
                assert (successor.root / "inbox" / str(remembered["inbox"])).read_text() == "concurrent inbox survives"
            finally:
                service.close()


def test_killed_preparing_writer_releases_locks_and_keeps_active_memory(tmp_path: Path) -> None:
    config, original, page = seed(tmp_path)
    with worker(compile_worker, config) as (process, control):
        event = receive(control)
        assert event["event"] == "preparing"
        process.kill()
        process.join(10)
        assert process.exitcode is not None
        _ = anyio.run(read_mcp, config, page, original)
        with worker(remember_worker, config) as (_remember, next_control):
            assert receive(next_control)["event"] == "ready"
            next_control.send("continue")
            completed = receive(next_control)
            assert completed["event"] == "completed" and completed["parent"] == original


def test_tombstone_accepted_during_preparation_prevents_stale_activation(tmp_path: Path) -> None:
    config, original, page = seed(tmp_path)
    with worker(compile_worker, config) as (_process, control):
        assert receive(control)["event"] == "preparing"
        values = executor_config(tmp_path)
        executor = RequestExecutor(values)
        try:
            request = effect_request(executor.generations.active(), "forget", "ExampleAlpha 예시기록",
                                     NOW, executor.store.tombstone_high_water(),
                                     Ed25519PrivateKey.from_private_bytes(bytes(range(32))), "f")
            _ = accept_effect_request(values.request_root, request, NOW, public_keys=values.jarvis_public_keys,
                                      provider_instance_id=values.provider_instance_id)
            assert executor.store.tombstone_high_water()[0] == 1
            anyio.run(reject_stale_generation, config, page, executor.store.tombstone_high_water())
            control.send("continue")
            assert receive(control) == {"event": "error", "code": "TOMBSTONE_SET_STALE"}
            assert executor.generations.active().generation_id == original
            assert not tuple(executor.generations.staging.iterdir())
            assert executor.apply_once(now=NOW).state == "proved"
            active = executor.generations.active()
            assert active.manifest.tombstone_sequence == 1
            assert all("ExampleAlpha" not in page.read_text() for page in active.root.joinpath("wiki").glob("*.md"))
        finally:
            executor.close()


def test_expired_export_cannot_be_reported_available_when_cleanup_is_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _original, _page = seed(tmp_path)
    now = datetime.now(UTC)
    values = executor_config(tmp_path)
    executor = RequestExecutor(values)
    try:
        request = effect_request(executor.generations.active(), "export", "ExampleAlpha 예시기록", now,
                                 executor.store.tombstone_high_water(),
                                 Ed25519PrivateKey.from_private_bytes(bytes(range(32))), "e")
        accepted = accept_effect_request(values.request_root, request, now, public_keys=values.jarvis_public_keys,
                                         provider_instance_id=values.provider_instance_id)
        applied = executor.apply_once(now=now)
        assert applied.state == "proved", applied
        export = values.export_root / accepted.request_id
        assert export.is_dir()
        with worker(compile_worker, config) as (_process, control):
            assert receive(control)["event"] == "preparing"

            class AfterExpiry(datetime):
                @classmethod
                @override
                def now(cls, tz: tzinfo | None = None) -> Self:
                    return cls.fromtimestamp((now + timedelta(days=2)).timestamp(), tz)

            monkeypatch.setenv("SB_CONFIG", str(config))
            monkeypatch.setattr(mcp_module, "datetime", AfterExpiry)

            async def status(expired: bool) -> None:
                async with Client(mcp_module.build_server(contract_schema=4), mode="legacy", cache=None) as client:
                    result = await client.call_tool("sb_request_status", {"request_id": accepted.request_id})
                    if not expired:
                        assert result.is_error and "EXPORT_EXPIRED" in str(result.content)
                    else:
                        assert not result.is_error
                        payload = cast(dict[str, object], result.structured_content)
                        assert cast(dict[str, object], payload["export_status"])["state"] == "expired"

            anyio.run(status, False)
            assert export.is_dir()  # Deferred cleanup is not claimed as physical deletion.
            control.send("continue")
            assert receive(control)["event"] == "completed"
            anyio.run(status, True)
            assert not export.exists()
    finally:
        executor.close()
