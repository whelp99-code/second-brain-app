from __future__ import annotations

import multiprocessing
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import TypeAdapter

from sb.cancellation_target import verify_cancellation_target
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import Generation
from sb.request_executor import RequestExecutor
from tests.test_cancellation_admission_binding import STAMP, admit
from tests.test_correction_cancellation_executor import prepare_unaccepted
from tests.test_request_executor import config as _config


def writer_process(root: str, entered: Event, release: Event, result: Queue[str], pause: bool, ready: Event, begin: Event) -> None:
    executor = RequestExecutor(_config(Path(root)))
    ready.set()
    assert begin.wait(20)

    def barrier(phase: str) -> None:
        if pause and phase == "successor_creation":
            entered.set()
            assert release.wait(20)

    try:
        if not pause:
            entered.set()
        _ = executor.mutations.mutate(GenerationMutation(
            mutation_id="concurrent-normal-writer", operation=GenerationOperation.RUN, now=STAMP,
            authority=GenerationAuthority(None, None), apply=lambda _root: None, barrier=barrier,
        ))
        result.put("writer_completed")
    except (RuntimeError, ValueError) as exc:
        result.put(str(exc))
    finally:
        executor.close()


def cancellation_process(root: str, value: JsonObject, entered: Event, release: Event, result: Queue[str], pause: bool, ready: Event, begin: Event) -> None:
    import sb.correction_cancellation_requests as requests

    executor = RequestExecutor(_config(Path(root)))
    ready.set()
    assert begin.wait(20)
    real_verify = verify_cancellation_target

    def verify_and_pause(generation: Generation, intent: CorrectionCancellationIntentV1) -> None:
        _ = real_verify(generation, intent)
        if pause:
            entered.set()
            assert release.wait(20)

    try:
        if not pause:
            entered.set()
        # The real target check and all real locks remain in use; only the release is controlled.
        with patch.object(requests, "verify_cancellation_target", verify_and_pause):
            accepted, replayed = admit(executor, value)
        assert not replayed and accepted["state"] == "suppression_pending"
        result.put("cancellation_accepted")
    except (RuntimeError, ValueError) as exc:
        result.put(str(exc))
    finally:
        executor.close()


@pytest.mark.parametrize("first", ["writer", "cancellation"])
def test_actual_generation_writer_and_cancellation_admission_are_serialized(tmp_path: Path, first: str):
    executor, value, _original = prepare_unaccepted(tmp_path)
    base = executor.generations.active().generation_id
    executor.close()
    ctx = multiprocessing.get_context("spawn")
    entered, started, release = ctx.Event(), ctx.Event(), ctx.Event()
    writer_result, cancellation_result = ctx.Queue(), ctx.Queue()
    writer_ready, cancellation_ready, writer_begin, cancellation_begin = (ctx.Event() for _ in range(4))
    writer = ctx.Process(target=writer_process, args=(str(tmp_path),
        entered if first == "writer" else started, release, writer_result, first == "writer", writer_ready, writer_begin))
    cancellation = ctx.Process(target=cancellation_process, args=(str(tmp_path), value,
        entered if first == "cancellation" else started, release, cancellation_result, first == "cancellation", cancellation_ready, cancellation_begin))
    leading, trailing = (writer, cancellation) if first == "writer" else (cancellation, writer)
    writer.start()
    cancellation.start()
    try:
        assert writer_ready.wait(20) and cancellation_ready.wait(20)
        (writer_begin if first == "writer" else cancellation_begin).set()
        assert entered.wait(20)
        (cancellation_begin if first == "writer" else writer_begin).set()
        assert started.wait(20)
        release.set()
        actual = (writer_result.get(timeout=20), cancellation_result.get(timeout=20))
        assert actual == (("writer_completed", "EFFECT_PRIOR_STALE") if first == "writer"
            else ("TOMBSTONE_SET_STALE", "cancellation_accepted"))
    finally:
        release.set()
        writer_begin.set()
        cancellation_begin.set()
        for process in (leading, trailing):
            if process.pid is not None:
                process.join(20)
                if process.is_alive():
                    process.kill()
                    process.join()
                assert process.exitcode == 0
    observer = RequestExecutor(_config(tmp_path))
    try:
        assert observer.store.tombstone_high_water()[0] == (0 if first == "writer" else 1)
        aliases = TypeAdapter(int).validate_python(observer.store.db.execute("SELECT count(*) FROM correction_cancellation_aliases").fetchone()[0], strict=True)
        assert aliases == (0 if first == "writer" else 8)
        assert (observer.generations.active().generation_id == base) == (first == "cancellation")
    finally:
        observer.close()
