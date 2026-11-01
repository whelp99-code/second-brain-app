"""Independent processes share a kernel lock, SQLite and isolated NV commitment."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import sqlite3
from contextlib import closing
from multiprocessing.connection import Connection, wait
from pathlib import Path
from typing import Protocol

import pytest

from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness_models import Checkpoint, ReserveProgressRequest
from tests.test_company_db_freshness import (
    PROVIDER_SCOPE,
    RECEIPT_BINDING,
    freshness_read,
    provider_at,
)


class SharedTestNv:
    """Disk-backed simulation for process tests, never a production provider kind."""

    def __init__(self, path: Path) -> None:
        self.path: Path = path

    def identity(self) -> str:
        return "sim-1"

    def public_name(self) -> bytes:
        return b"\x22" * 32

    def read_value(self) -> bytes:
        value = self.path.read_bytes()
        assert len(value) == 32
        return value

    def extend(self, record_digest_raw: bytes) -> bytes:
        value = hashlib.sha256(self.read_value() + record_digest_raw).digest()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            assert os.pwrite(descriptor, value, 0) == 32
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return value


class StartBarrier(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...


def reserve_worker(
    root: str,
    expected: str,
    request_id: str,
    output: Connection,
    start: StartBarrier,
) -> None:
    path = Path(root)
    provider = CompanyDbFreshnessProvider(
        database=path / "company.db",
        actor_store="second_brain",
        registry_path=path / "freshness-registry.json",
        witness_dir=path / "witness",
        lock_path=path / "registry.lock",
        anchor=SharedTestNv(path / "isolated-nv.bin"),
        registry_id="company-freshness:linux:v1",
    )
    _ = start.wait(timeout=20)
    result = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id_for(
                PROVIDER_SCOPE,
                request_id=request_id,
                command_digest=RECEIPT_BINDING,
                operation="accept",
            ),
            operation="accept",
            expected_checkpoint=Checkpoint.model_validate_json(expected, strict=True),
            event_digest=RECEIPT_BINDING,
            challenge="process:" + request_id,
        )
    )
    output.send_bytes(result.outcome.encode("ascii"))
    output.close()


@pytest.mark.parametrize("same_operation", [False, True])
def test_process_cas_and_permanent_operation_dedup(tmp_path: Path, same_operation: bool) -> None:
    provider = provider_at(tmp_path)
    checkpoint = provider.read_freshness(freshness_read(provider)).checkpoint
    assert checkpoint is not None
    nv_path = tmp_path / "isolated-nv.bin"
    _ = nv_path.write_bytes(provider.anchor.read_value())
    provider.anchor = SharedTestNv(nv_path)
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(3)
    pipes = [context.Pipe(duplex=False) for _ in range(2)]
    processes = [
        context.Process(
            target=reserve_worker,
            args=(
                str(tmp_path),
                checkpoint.model_dump_json(),
                "race:same" if same_operation else f"race:{index}",
                writer,
                start,
            ),
        )
        for index, (_reader, writer) in enumerate(pipes)
    ]
    try:
        for process in processes:
            process.start()
        for _reader, writer in pipes:
            writer.close()
        _ = start.wait(timeout=20)
        responses: list[str] = []
        for reader, _writer in pipes:
            assert wait([reader], timeout=20)
            responses.append(reader.recv_bytes().decode("ascii"))
        for process in processes:
            assert wait([process.sentinel], timeout=20)
            process.join()
            assert process.exitcode == 0
        assert sorted(responses) == (
            ["already_reserved", "reserved"] if same_operation else ["conflict", "reserved"]
        )
        with closing(sqlite3.connect(provider.database)) as db:
            reserved: list[tuple[str]] = db.execute(
                "SELECT next_nv FROM company_freshness_log WHERE phase='reserve'",
            ).fetchall()
            operations: list[tuple[int]] = db.execute(
                "SELECT count(*) FROM company_freshness_operations",
            ).fetchall()
        assert reserved == [(provider.anchor.read_value().hex(),)]
        assert operations == [(1,)]
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join()
        for reader, writer in pipes:
            reader.close()
            writer.close()
