"""Actual process death at every durable publication boundary, with one SQL effect."""

from __future__ import annotations

import multiprocessing
import signal
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from multiprocessing.connection import wait
from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_kill_worker import KillBoundary, kill_auto_worker
from tests.company_internal_auto_support import contact_body, receive, trigger
from tests.test_company_db_concurrency import SharedTestNv


@pytest.mark.parametrize("boundary", ["prepare", "fsync", "extend", "publication", "ack"])
def test_sigkill_recovers_original_auto_completion_once(
    tmp_path: Path, boundary: KillBoundary
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "kill:original", "event:kill:original", contact_body())
    anchor = tmp_path / "isolated-nv.bin"
    _ = anchor.write_bytes(provider.anchor.read_value())
    provider.anchor = SharedTestNv(anchor)
    process_context = multiprocessing.get_context("spawn")
    reader, writer = process_context.Pipe(duplex=False)
    child = process_context.Process(
        target=kill_auto_worker,
        args=(
            str(tmp_path),
            settings.policy.model_dump_json(),
            settings.signer.private_key.private_bytes_raw(),
            settings.signer.key_id,
            boundary,
            writer,
        ),
    )
    try:
        child.start()
        writer.close()
        assert wait([child.sentinel], timeout=20)
        child.join()
        assert child.exitcode == -signal.SIGKILL
        if boundary == "ack":
            assert wait([reader], timeout=20)
            assert reader.recv_bytes() == b"recorded"
        with closing(sqlite3.connect(provider.database)) as db:
            original: list[tuple[str]] = db.execute(
                "SELECT receipt_json FROM company_auto_policy_receipts",
            ).fetchall()
            committed: list[tuple[int]] = db.execute(
                "SELECT count(*) FROM company_internal_effects",
            ).fetchall()
        assert committed == [(1,)]
        _ = run_auto_internal(
            provider.database,
            settings,
            replace(context, now=context.now + timedelta(minutes=10)),
            provider,
            trigger(context.now + timedelta(minutes=10)),
        )
        with closing(sqlite3.connect(provider.database)) as db:
            retained: list[tuple[str]] = db.execute(
                "SELECT receipt_json FROM company_auto_policy_receipts",
            ).fetchall()
            counts: list[tuple[int, int, int]] = db.execute(
                """SELECT (SELECT count(*) FROM company_internal_effects),
                (SELECT count(*) FROM company_internal_records),
                (SELECT count(*) FROM company_internal_pending_finish)""",
            ).fetchall()
            states: list[tuple[str]] = db.execute(
                "SELECT state FROM company_memory_candidates",
            ).fetchall()
            finishes: list[tuple[int]] = db.execute(
                """SELECT count(*) FROM company_freshness_log
                WHERE phase='finish' AND json_extract(record_json,'$.terminal_state')='completed'""",
            ).fetchall()
        assert retained == original
        assert counts == [(1, 1, 0)]
        assert states == [("processed_complete",)]
        assert finishes == [(1,)]
    finally:
        if child.is_alive():
            child.kill()
            child.join()
        reader.close()
        writer.close()
        child.close()
