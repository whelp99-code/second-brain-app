from __future__ import annotations

import multiprocessing
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sb.effect_write_requests import accept_effect_request
from sb.request_executor import RequestExecutor
from tests.test_cancellation_admission_binding import STAMP, admit
from tests.test_correction_cancellation_executor import (
    OLD,
    REPLACEMENT,
    execute,
    prepare_unaccepted,
)
from tests.test_request_executor import _config


def admission_actor(root, value, kind, pause, ready, begin, entered, release, results):
    import sb.correction_cancellation_requests as cancellation
    import sb.effect_write_requests as publication

    executor = RequestExecutor(_config(Path(root)))
    original = publication._publish if kind == "request" else cancellation.verify_cancellation_target

    def at_locked_boundary(*args, **kwargs):
        # Both hooks run with the real pending-directory admission mutex held.
        if pause:
            entered.set()
            assert release.wait(20)
        return original(*args, **kwargs)

    ready.set()
    try:
        assert begin.wait(20)
        if not pause:
            entered.set()
        if kind == "request":
            with patch.object(publication, "_publish", at_locked_boundary):
                accepted = accept_effect_request(executor.config.request_root, value, STAMP,
                    public_keys=executor.config.jarvis_public_keys,
                    provider_instance_id=executor.config.provider_instance_id)
            result = ("request_accepted", accepted.request_id)
        else:
            with patch.object(cancellation, "verify_cancellation_target", at_locked_boundary):
                accepted, replayed = admit(executor, value)
            assert not replayed
            result = ("cancellation_accepted", accepted["intent_id"])
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
    actors = {}
    for kind, value in (("request", request), ("cancellation", intent)):
        ready, begin, entered, results = ctx.Event(), ctx.Event(), ctx.Event(), ctx.Queue()
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
        count = restarted.store.db.execute("SELECT count(*) FROM correction_cancellations").fetchone()[0]
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
            assert execute(restarted, accepted["intent_id"])["state"] == "generation_active"
            assert restarted.store.get(request["request_id"]) is None
        assert restarted.apply_once(now=STAMP).state == "idle"
        active = restarted.generations.active()
        files = subprocess.check_output(["git", "-C", str(active.root), "ls-tree", "-r", "--name-only", "HEAD", "wiki"], text=True).splitlines()
        committed = "\n".join(subprocess.check_output(["git", "-C", str(active.root), "show", f"HEAD:{name}"], text=True) for name in files)
        assert OLD not in committed
        assert (REPLACEMENT in committed) == (first == "request")
    finally:
        restarted.close()


def publish_then_exit(root, request):
    import os

    import sb.effect_write_requests as publication

    original = publication._publish

    def stop_after_publication(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(77)

    config = _config(Path(root))
    with patch.object(publication, "_publish", stop_after_publication):
        publication.accept_effect_request(config.request_root, request, STAMP,
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
            admit(restarted, intent)
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
