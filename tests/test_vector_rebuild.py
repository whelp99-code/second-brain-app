"""Native SQLite rebuild failure/publication boundaries with deterministic vectors."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import pytest

from sb import embeddings
from sb.embeddings import VECTOR_DIM, EmbeddingUnavailable, ModelIdentity
from sb.hybrid_search import query_cosine
from sb.search import git_run
from tests.knowledge import commit_page
from tests.test_embeddings import (
    FakeEncoder,
    _ready,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional extra missing")

class BrokenEncoder:
    identity: ModelIdentity = FakeEncoder().identity

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        del texts
        raise EmbeddingUnavailable("fixture encode failed")


def test_failed_encoding_preserves_previous_database(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    path = embeddings.vectors_path(root)
    before = path.read_bytes()
    with pytest.raises(EmbeddingUnavailable):
        _ = embeddings.rebuild(root, encoder=BrokenEncoder())
    assert path.is_file() and path.read_bytes() == before


def test_large_rebuild_does_not_use_one_oversized_argument(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    # 48 distinct sections produce >128 KiB of SQL with ordinary float vectors.
    body = "\n".join(f"# Section {i}\nLargeNeedle synthetic section {i}." for i in range(48))
    commit_page(root, "wiki/large.md", body)
    assert embeddings.rebuild(root, encoder=FakeEncoder()) >= 48


def test_short_encoder_result_preserves_previous_database(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    path = embeddings.vectors_path(root)
    before = path.read_bytes()

    class ShortEncoder:
        identity: ModelIdentity = FakeEncoder().identity

        def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            del texts
            return ((1.0,) + (0.0,) * (VECTOR_DIM - 1),)

    with pytest.raises(EmbeddingUnavailable):
        _ = embeddings.rebuild(root, encoder=ShortEncoder())
    assert path.read_bytes() == before


def test_sealed_root_is_not_mutated_by_standalone_rebuild(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    _ = (root / "generation.json").write_text("{}")
    path = embeddings.vectors_path(root)
    before = path.read_bytes()
    with pytest.raises(EmbeddingUnavailable):
        _ = embeddings.rebuild(root, encoder=FakeEncoder())
    assert path.read_bytes() == before


def test_reader_remains_available_and_second_writer_is_rejected(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    before = embeddings.vectors_path(root).read_bytes()

    class ObservingEncoder:
        identity: ModelIdentity = FakeEncoder().identity

        def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            assert query_cosine(root, "AlphaEngineer", 1, encoder=FakeEncoder())
            assert embeddings.vectors_path(root).read_bytes() == before
            with pytest.raises(EmbeddingUnavailable, match="already in progress"):
                _ = embeddings.rebuild(root, encoder=FakeEncoder())
            return FakeEncoder().encode(texts)

    assert embeddings.rebuild(root, encoder=ObservingEncoder()) == 3


def test_open_reader_retains_old_database_after_atomic_replacement(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    path = embeddings.vectors_path(root)
    reader = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        _ = reader.execute("BEGIN")
        assert reader.execute("SELECT count(*) FROM chunks").fetchone() == (3,)
        commit_page(root, "wiki/new.md", "New persistent reader fixture")
        assert embeddings.rebuild(root, encoder=FakeEncoder()) == 4
        assert reader.execute("SELECT count(*) FROM chunks").fetchone() == (3,)
        assert embeddings.run_vec_sql(path, "SELECT count(*) FROM chunks;", read_only=True) == "4\x1e"
    finally:
        reader.close()


def test_sql_failure_preserves_database_and_cleans_own_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ready(tmp_path)
    path = embeddings.vectors_path(root)
    before, entries = path.read_bytes(), set(path.parent.iterdir())

    def fail(staging: Path, script: TextIO, *, lock_fd: int) -> None:
        del script, lock_fd
        _ = embeddings.run_vec_sql(staging, "CREATE TABLE partial(value TEXT);")
        raise EmbeddingUnavailable("fixture SQL failure")

    monkeypatch.setattr(embeddings, "run_vec_script", fail)
    with pytest.raises(EmbeddingUnavailable, match="fixture SQL failure"):
        _ = embeddings.rebuild(root, encoder=FakeEncoder())
    assert path.read_bytes() == before
    assert set(path.parent.iterdir()) == entries


@pytest.mark.parametrize("vector", [(), (1.0,), (0.0,) * VECTOR_DIM,
    (float("nan"),) * VECTOR_DIM, (float("inf"),) * VECTOR_DIM,
    (1e100,) * VECTOR_DIM, (1e-100,) * VECTOR_DIM,
    (1e30,) * VECTOR_DIM, (1e-30,) * VECTOR_DIM])
def test_invalid_vectors_preserve_database(tmp_path: Path, vector: tuple[float, ...]) -> None:
    root = _ready(tmp_path)
    before = embeddings.vectors_path(root).read_bytes()

    class InvalidEncoder:
        identity: ModelIdentity = FakeEncoder().identity

        def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            return (vector,) * len(texts)

    with pytest.raises(EmbeddingUnavailable, match="invalid embedding vector"):
        _ = embeddings.rebuild(root, encoder=InvalidEncoder())
    assert embeddings.vectors_path(root).read_bytes() == before


def test_changed_git_head_cannot_publish_stale_rebuild(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    before = embeddings.vectors_path(root).read_bytes()

    class ChangingEncoder:
        identity: ModelIdentity = FakeEncoder().identity

        def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            commit_page(root, "wiki/new.md", "source changed during encode")
            return FakeEncoder().encode(texts)

    with pytest.raises(EmbeddingUnavailable, match="source changed"):
        _ = embeddings.rebuild(root, encoder=ChangingEncoder())
    assert embeddings.vectors_path(root).read_bytes() == before


def test_failed_git_enumeration_does_not_publish_empty_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ready(tmp_path)
    before = embeddings.vectors_path(root).read_bytes()
    def unavailable(*args: object) -> None:
        del args

    monkeypatch.setattr("sb.search._git_run_bytes", unavailable)
    with pytest.raises(EmbeddingUnavailable, match="paths unavailable"):
        _ = embeddings.rebuild(root, encoder=FakeEncoder())
    assert embeddings.vectors_path(root).read_bytes() == before


def test_streamed_text_preserves_utf8_quotes_nul_and_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ready(tmp_path)
    body = "한글 'quotes'\r\n.shell touch should-never-exist\n lone\r tab\t nul\x00 rs\x1e"
    # Exercise transport after section parsing, whose existing normalization is separate.
    def collect(*args: object, **kwargs: object) -> tuple[tuple[str, str, str, str], ...]:
        del args, kwargs
        return (("wiki/special", "Section\r\n'한글'", body, "fixture-digest"),)

    monkeypatch.setattr(embeddings, "collect_chunks", collect)
    assert embeddings.rebuild(root, encoder=FakeEncoder()) == 1
    raw = embeddings.run_vec_sql(embeddings.vectors_path(root),
                                 "SELECT hex(text) FROM chunks;", read_only=True)
    assert raw == body.encode().hex().upper() + "\x1e"
    head = git_run(root, "rev-parse", "HEAD")
    assert head is not None
    assert embeddings.run_vec_sql(embeddings.vectors_path(root),
        "SELECT git_head FROM embedding_meta;", read_only=True) == head.strip() + "\x1e"


def test_cli_rebuild_handles_bulk_sql_in_native_subprocess(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    commit_page(root, "wiki/large.md", "\n".join(f"# S{i}\nLargeCLI fixture {i}" for i in range(128)))
    env = dict(os.environ, SB_VAULT=str(root))
    done = subprocess.run([sys.executable, "-c",
        ("from sb import embeddings as e;from tests.test_embeddings import FakeEncoder;"
        "e.resolve_encoder=FakeEncoder;raise SystemExit(e.main(['rebuild']))")],
        env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "rebuilt 131 vectors\n"
    assert query_cosine(root, "LargeCLI", 1, encoder=FakeEncoder())[0].page_id == "wiki/large"


def test_process_exit_preserves_search_and_releases_writer_lock(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    path = embeddings.vectors_path(root)
    before = path.read_bytes()
    program = (
        "import os\nfrom pathlib import Path\nfrom sb.embeddings import rebuild\n"
        "from tests.test_embeddings import FakeEncoder\n"
        "class CrashEncoder:\n identity=FakeEncoder().identity\n"
        " def encode(self,texts): os._exit(17)\n"
        "rebuild(Path(os.environ['SB_VAULT']),encoder=CrashEncoder())\n"
    )
    done = subprocess.run([sys.executable, "-c", program],
        env=dict(os.environ, SB_VAULT=str(root)), capture_output=True, text=True, check=False)
    assert done.returncode == 17, done.stderr
    assert path.read_bytes() == before
    assert query_cosine(root, "AlphaEngineer", 1, encoder=FakeEncoder())
    orphans = set(path.parent.glob(".vectors-*.db"))
    assert len(orphans) == 1
    assert embeddings.rebuild(root, encoder=FakeEncoder()) == 3
    # Hosts with unreadable same-owner process descriptors defer orphan cleanup.
    assert set(path.parent.glob(".vectors-*.db")) <= orphans


def test_failed_postbuild_validation_preserves_previous_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ready(tmp_path)
    before = embeddings.vectors_path(root).read_bytes()

    def bad_check(*args: object, **kwargs: object) -> str:
        del args, kwargs
        return "corrupt\x1e"

    monkeypatch.setattr(embeddings, "run_vec_sql", bad_check)
    with pytest.raises(EmbeddingUnavailable, match="validation failed"):
        _ = embeddings.rebuild(root, encoder=FakeEncoder())
    assert embeddings.vectors_path(root).read_bytes() == before
