from __future__ import annotations

import multiprocessing
import subprocess
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import TypeAdapter

from sb.cancellation_target import verify_cancellation_target
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonValue
from sb.effect_write_requests import PendingPublication, accept_effect_request
from sb.generations import Generation
from sb.request_executor import RequestExecutor
from tests.test_cancellation_admission_binding import STAMP, admit
from tests.test_correction_cancellation_executor import (
    OLD,
    REPLACEMENT,
    execute,
    prepare_unaccepted,
)
from tests.test_request_executor import config as _config


def admission_actor(root: str, value: JsonValue, kind: str, pause: bool, ready: Event, begin: Event, entered: Event, release: Event, results: Queue[tuple[str, str]]) -> None:
    import sb.correction_cancellation_requests as cancellation
    import sb.effect_write_requests as publication

    executor = RequestExecutor(_config(Path(root)))
    original_publish = publication.publish
    original_verify = verify_cancellation_target

    def at_locked_boundary() -> None:
        # Both hooks run with the real pending-directory admission mutex held.
        if pause:
            entered.set()
            assert release.wait(20)

    def publish(directory: int, pending: PendingPublication) -> None:
        at_locked_boundary()
        original_publish(directory, pending)

    def verify(generation: Generation, intent: CorrectionCancellationIntentV1) -> bytes:
        at_locked_boundary()
        return original_verify(generation, intent)

    ready.set()
    try:
        assert begin.wait(20)
        if not pause:
            entered.set()
        if kind == "request":
            with patch.object(publication, "publish", publish):
                accepted = accept_effect_request(executor.config.request_root, value, STAMP,
                    public_keys=executor.config.jarvis_public_keys,
                    provider_instance_id=executor.config.provider_instance_id)
            result = ("request_accepted", accepted.request_id)
        else:
            with patch.object(cancellation, "verify_cancellation_target", verify):
                accepted, replayed = admit(executor, value)
            assert not replayed
            intent_id = accepted["intent_id"]
            assert isinstance(intent_id, str)
            result = ("cancellation_accepted", intent_id)
        results.put(result)
    except (RuntimeError, ValueError) as exc:
        results.put((type(exc).__name__, str(exc)))
    finally:
        executor.close()


@pytest.mark.parametrize("first", ["request", "cancellation"])
def test_same_request_publication_and_cancellation_have_one_winner(tmp_path: Path, first: str):
    executor, intent, request = prepare_unaccepted(tmp_path)
    executor.close()
    ctx = multiprocessing.get_context("spawn")
    release = ctx.Event()
    actors: dict[str, tuple[BaseProcess, Event, Event, Event, Queue[tuple[str, str]]]] = {}
    for kind, value in (("request", request), ("cancellation", intent)):
        ready, begin, entered = ctx.Event(), ctx.Event(), ctx.Event()
        results: Queue[tuple[str, str]] = ctx.Queue()
        process = ctx.Process(target=admission_actor, args=(str(tmp_path), value, kind, kind == first,
            ready, begin, entered, release, results))
        actors[kind] = (process, ready, begin, entered, results)
        process.start()
    second = "cancellation" if first == "request" else "request"
    try:
        assert all(row[1].wait(20) for row in actors.values())
        actors[first][2].set()
        assert actors[first][3].wait(20)
        actors[second][2].set()
        assert actors[second][3].wait(20)
        release.set()
        observed = {kind: row[4].get(timeout=20) for kind, row in actors.items()}
        assert observed[first][0] == first + "_accepted", observed
        assert observed[second][1] == ("MEMORY_CANCELLATION_ALREADY_RECEIVED" if first == "request"
            else "MEMORY_REQUEST_CANCELLED"), observed
    finally:
        release.set()
        for process, _ready, begin, _entered, _result in actors.values():
            begin.set()
            process.join(20)
            if process.is_alive():
                process.kill()
                process.join()
            assert process.exitcode == 0

    restarted = RequestExecutor(_config(tmp_path))
    try:
        assert restarted.store.tombstone_high_water()[0] == 1
        count = TypeAdapter(int).validate_python(
            restarted.store.db.execute("SELECT count(*) FROM correction_cancellations").fetchone()[0], strict=True,
        )
        assert count == int(first == "cancellation")
        if first == "request":
            replay = accept_effect_request(restarted.config.request_root, request, STAMP,
                public_keys=restarted.config.jarvis_public_keys,
                provider_instance_id=restarted.config.provider_instance_id)
            assert replay.replayed
            assert restarted.apply_once(now=STAMP).state == "proved"
        else:
            assert isinstance(request['request_id'], str)
            accepted, replayed = admit(restarted, intent)
            assert replayed
            intent_id = accepted["intent_id"]
            assert isinstance(intent_id, str)
            assert execute(restarted, intent_id)["state"] == "generation_active"
            assert restarted.store.get(request["request_id"]) is None
        assert restarted.apply_once(now=STAMP).state == "idle"
        active = restarted.generations.active()
        files = subprocess.check_output(["git", "-C", str(active.root), "ls-tree", "-r", "--name-only", "HEAD", "wiki"], text=True).splitlines()
        committed = "\n".join(subprocess.check_output(["git", "-C", str(active.root), "show", f"HEAD:{name}"], text=True) for name in files)
        assert OLD not in committed
        assert (REPLACEMENT in committed) == (first == "request")
    finally:
        restarted.close()


def publish_then_exit(root: str, request: JsonValue) -> None:
    import os

    import sb.effect_write_requests as publication

    original = publication.publish

    def stop_after_publication(directory: int, pending: PendingPublication) -> None:
        original(directory, pending)
        os._exit(77)

    config = _config(Path(root))
    with patch.object(publication, "publish", stop_after_publication):
        _ = publication.accept_effect_request(config.request_root, request, STAMP,
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)


def test_exit_after_request_file_publication_blocks_cancellation_and_recovers(tmp_path: Path):
    from sb.request_store import ReplayConflict

    executor, intent, request = prepare_unaccepted(tmp_path)
    executor.close()
    process = multiprocessing.get_context("spawn").Process(target=publish_then_exit, args=(str(tmp_path), request))
    process.start()
    process.join(20)
    if process.is_alive():
        process.kill()
        process.join()
    assert process.exitcode == 77
    restarted = RequestExecutor(_config(tmp_path))
    try:
        assert isinstance(request['request_id'], str)
        assert restarted.store.get(request["request_id"]) is None
        assert restarted.store.tombstone_high_water()[0] == 0
        assert list(restarted.config.request_root.joinpath("pending").glob("*.v2.json"))
        with pytest.raises(ReplayConflict, match="MEMORY_CANCELLATION_ALREADY_RECEIVED"):
            _ = admit(restarted, intent)
        assert restarted.store.db.execute("SELECT count(*) FROM correction_cancellations").fetchone()[0] == 0
        accepted = accept_effect_request(restarted.config.request_root, request, STAMP,
            public_keys=restarted.config.jarvis_public_keys,
            provider_instance_id=restarted.config.provider_instance_id)
        assert accepted.request_id == request["request_id"]
        assert restarted.store.tombstone_high_water()[0] == 1
        assert restarted.apply_once(now=STAMP).state == "proved"
        assert restarted.apply_once(now=STAMP).state == "idle"
    finally:
        restarted.close()
