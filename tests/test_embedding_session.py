"""Native bounded batch protocol and model lifetime; no sleeps or external models."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from sb import embedding_session
from sb.embedding_session import ModelSession
from sb.embeddings import EmbeddingUnavailable
from tests.test_embedding_process import IDENTITY, encoder
from tests.test_generation_vectors import (
    _build,  # pyright: ignore[reportPrivateUsage]
    _page,  # pyright: ignore[reportPrivateUsage]
    _store,  # pyright: ignore[reportPrivateUsage]
)


def fake_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "loads"
    monkeypatch.setenv("MODEL_LOADS", str(path))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    _ = (tmp_path / "sentence_transformers.py").write_text(
        "import os\nfrom pathlib import Path\n"
        + "class SentenceTransformer:\n"
        + " def __init__(self, name, *, revision, local_files_only=False):\n"
        + "  assert local_files_only\n"
        + "  with Path(os.environ['MODEL_LOADS']).open('a') as f: f.write(str(os.getpid())+'\\n')\n"
        + " def encode(self, texts, *, normalize_embeddings):\n"
        + "  assert normalize_embeddings\n"
        + "  return [[1.0] + [0.0] * 1023 for _ in texts]\n")
    return path


def test_one_model_handles_multiple_large_pipe_batches_and_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loads = fake_model(tmp_path, monkeypatch)
    with ModelSession(IDENTITY) as session:
        assert session.encode(()) == () and not loads.exists()
        result = session.encode(tuple("기억" * 1024 for _ in range(64)))
        assert len(result) == 64 and all(row == (1.0,) + (0.0,) * 1023 for row in result)
        assert session.encode(("두 번째",)) == ((1.0,) + (0.0,) * 1023,)
        pids = [int(line) for line in loads.read_text().splitlines()]
        assert len(pids) == 1
        os.kill(pids[0], 0)
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    with pytest.raises(EmbeddingUnavailable, match="closed"):
        _ = session.encode(("after close",))


def test_generation_only_loads_for_changed_records_and_reuses_all_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads = fake_model(tmp_path, monkeypatch)
    _ = encoder(tmp_path, monkeypatch)
    store = _store(tmp_path)
    pages = {f"p{i:03}": _page(f"기억 {i}") for i in range(65)}
    try:
        first = _build(store, pages)
        assert len(loads.read_text().splitlines()) == 1
        second = _build(store, pages, first)
        assert len(loads.read_text().splitlines()) == 1
        pages["p100"] = _page("새 기억")
        _ = _build(store, pages, second)
        pids = [int(line) for line in loads.read_text().splitlines()]
        assert len(pids) == 2
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        store.close()


@pytest.mark.parametrize("reply", ["{}", "[]", "diagnostic text", '{"id": 9}', "{}\n{}", "x" * 1025])
def test_bad_frames_terminate_and_reap_the_worker(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    monkeypatch.setattr(embedding_session, "_MAX_FRAME", 1024)
    monkeypatch.setattr(embedding_session, "_SCRIPT", "import sys\nsys.stdin.buffer.readline()\nprint(" + repr(reply) + ")")
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def spawn(args: Sequence[str], *, stdin: int, stdout: int, stderr: int, bufsize: int,
              pass_fds: tuple[int, ...]) -> subprocess.Popen[bytes]:
        process = original(args, stdin=stdin, stdout=stdout, stderr=stderr, bufsize=bufsize, pass_fds=pass_fds)
        children.append(process)
        return children[-1]

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(EmbeddingUnavailable), ModelSession(IDENTITY) as session:
        _ = session.encode(("fixture",))
    assert len(children) == 1 and children[0].poll() is not None


def test_blocked_pipe_write_has_deadline_and_worker_is_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_session, "_TIMEOUT", 0.1)
    monkeypatch.setattr(embedding_session, "_SCRIPT", "import threading\nthreading.Event().wait()")
    with ModelSession(IDENTITY) as session:
        with pytest.raises(EmbeddingUnavailable, match="timed out"):
            _ = session.encode(("x" * 1000000,))
        assert session._process is None  # pyright: ignore[reportPrivateUsage]


def test_nonzero_worker_exit_after_valid_response_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    script = ("import json,sys\nr=json.loads(sys.stdin.buffer.readline())\n"
              + "print(json.dumps({'id':r['id'],'model':sys.argv[1],'revision':sys.argv[2],"
              + "'vectors':[[1.0]+[0.0]*1023]}),flush=True)\nsys.exit(3)\n")
    monkeypatch.setattr(embedding_session, "_SCRIPT", script)
    with pytest.raises(EmbeddingUnavailable, match="did not exit cleanly"), ModelSession(IDENTITY) as session:
        assert len(session.encode(("fixture",))) == 1


def test_worker_has_its_own_model_start_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = (tmp_path / "sentence_transformers.py").write_text(
        "import threading\nclass SentenceTransformer:\n def __init__(self, *args, **kwargs): threading.Event().wait()\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    script = embedding_session._SCRIPT.replace("ITIMER_REAL, 60)", "ITIMER_REAL, 0.1)")  # pyright: ignore[reportPrivateUsage]
    process = subprocess.Popen([sys.executable, "-c", script,
        IDENTITY.model_id, IDENTITY.revision], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    try:
        _ = process.communicate(b"", timeout=5)
        assert process.returncode == -signal.SIGALRM
    finally:
        if process.poll() is None:
            process.kill()
        _ = process.wait()
