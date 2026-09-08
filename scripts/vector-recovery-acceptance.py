"""Native vector CLI crash/retry and unsafe-directory acceptance; synthetic data only."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from sb.embeddings import vectors_path
from sb.hybrid_search import query_cosine
from tests.knowledge import commit_page
from tests.test_embeddings import FakeEncoder, _ready  # pyright: ignore[reportPrivateUsage]

BOOTSTRAP = """import os
import sb.embeddings as embeddings
from tests.test_embeddings import FakeEncoder
embeddings.resolve_encoder = FakeEncoder
if os.environ.get('FIXTURE_CRASH') == 'yes':
    execute = embeddings.run_vec_script
    def crash(*args, **kwargs):
        execute(*args, **kwargs)
        os._exit(17)
    embeddings.run_vec_script = crash
raise SystemExit(embeddings.main(['rebuild']))
"""


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="sb-vector-recovery-"))
    repository = Path(__file__).resolve().parents[1]
    root = _ready(base)
    path = vectors_path(root)
    before = path.read_bytes()
    commit_page(root, "wiki/new.md", "New recovery fixture: undisclosed source-derived bytes")
    results: dict[str, object] = {}

    def cli(label: str, vault: Path, *, crash: bool = False) -> subprocess.CompletedProcess[str]:
        done = subprocess.run([sys.executable, "-c", BOOTSTRAP], capture_output=True,
                              text=True, check=False, timeout=60,
                              env=dict(os.environ, SB_VAULT=str(vault), PYTHONPATH=str(repository),
                                       FIXTURE_CRASH="yes" if crash else "no"))
        _ = (base / f"{label}.stdout").write_text(done.stdout)
        _ = (base / f"{label}.stderr").write_text(done.stderr)
        results[label] = {"exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr}
        return done

    reader = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        _ = reader.execute("BEGIN")
        assert reader.execute("SELECT count(*) FROM chunks").fetchone() == (3,)
        assert cli("crash-after-sql", root, crash=True).returncode == 17
        assert path.read_bytes() == before
        assert query_cosine(root, "AlphaEngineer", 1, encoder=FakeEncoder())
        orphaned = tuple(path.parent.glob(".vectors-*.db"))
        assert len(orphaned) == 1 and orphaned[0].stat().st_size > 0
        retry = cli("retry", root)
        assert retry.returncode == 0 and "rebuilt 4 vectors" in retry.stdout
        assert reader.execute("SELECT count(*) FROM chunks").fetchone() == (3,)
    finally:
        reader.close()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as current:
        assert current.execute("SELECT count(*) FROM chunks").fetchone() == (4,)
    remains = [p.name for p in orphaned if p.exists()]
    if remains:
        assert "cleanup deferred" in retry.stderr
    outside = base / "outside"
    outside.mkdir()
    external = outside / "vectors.db"
    _ = external.write_bytes(b"unrelated database")
    linked = base / "symlink-vault"
    linked.mkdir(mode=0o700)
    (linked / ".sb").symlink_to(outside, target_is_directory=True)
    denied = cli("unsafe-directory", linked)
    assert denied.returncode == 1 and denied.stdout == ""
    assert external.read_bytes() == b"unrelated database"
    assert list(outside.iterdir()) == [external]
    report = {"state": "passed", "workspace": str(base), "commands": results,
              "prior_vector_sha256": hashlib.sha256(before).hexdigest(),
              "reader_previous_rows": 3, "published_rows": 4, "old_search_after_crash": True,
              "unsafe_directory_unchanged": True, "remaining_orphans": remains,
              "cleanup_complete": not remains,
              "limitations": ["deterministic encoder; not model quality",
                              "standalone vectors, not sealed hybrid activation",
                              "unverifiable host reader visibility defers disposal"]}
    _ = (base / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
