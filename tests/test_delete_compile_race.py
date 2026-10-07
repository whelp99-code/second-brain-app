"""H3: generation writer serializes forget vs compile; forget-last stays empty."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sb.generation_locks import GenerationWriterBusy, generation_writer
from sb.search import SearchIndex
from sb.vault import Vault
from tests.test_web import TERM
from tests.test_web import ready as _ready


def test_second_writer_is_busy_while_forget_lock_held(tmp_path: Path) -> None:
    lock = tmp_path / "state" / "generation.lock"
    lock.parent.mkdir(parents=True)
    _ = lock.write_bytes(b"")
    with generation_writer(lock, blocking=True):  # noqa: SIM117
        with pytest.raises(GenerationWriterBusy, match="GENERATION_WRITER_BUSY"):
            with generation_writer(lock, blocking=False):
                pass


def test_forget_then_search_and_reindex_stay_empty(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    forgotten = Vault(root).forget_page("wiki/계약-일정")
    assert forgotten is not None
    assert SearchIndex(root, hybrid=False).search(TERM, 8) == ()
    assert SearchIndex(Path(config.vault_root), hybrid=False).search(TERM, 8) == ()


def test_subprocess_writers_serialize_then_forget_wins(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    lock = tmp_path / "state" / "generation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not lock.exists():
        _ = lock.write_bytes(b"")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    first = subprocess.Popen(
        [sys.executable, "-c", (
            "from pathlib import Path\n"
            "from sb.generation_locks import generation_writer\n"
            f"with generation_writer(Path({str(lock)!r}), blocking=True):\n"
            "    pass\n"
        )],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    second = subprocess.Popen(
        [sys.executable, "-c", (
            "from pathlib import Path\n"
            "from sb.generation_locks import generation_writer\n"
            f"with generation_writer(Path({str(lock)!r}), blocking=True):\n"
            "    pass\n"
        )],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    assert first.wait(timeout=30) == 0
    assert second.wait(timeout=30) == 0
    _ = Vault(root).forget_page("wiki/계약-일정")
    assert SearchIndex(root, hybrid=False).search(TERM, 8) == ()
