"""Separate configured source IDs isolate session roots across real CLI restarts."""

import os
import subprocess
import sys

import pytest

from sb.store.ledger import load_ledger_tables
from tests.test_session_file_replacement import FACTORIES, record


@pytest.mark.parametrize("kind", list(FACTORIES))
def test_explicit_sources_keep_independent_ledger_and_resume(tmp_path, kind):
    roots = [tmp_path / "agent-a", tmp_path / "agent-b"]
    for root in roots:
        root.mkdir()
        (root / "session.jsonl").write_bytes(record(kind, "same-id"))
    vault = tmp_path / "vault"
    config = tmp_path / "config.toml"
    config.write_text(
        f'vault_root = "{vault}"\nshare_root = "{tmp_path}"\nstate_root = "{tmp_path / "state"}"\n'
        + "".join(
            f'[[sources]]\nid = "agent-{i}"\nadapter = "{kind}-sessions"\nroot = "{root}"\n'
            for i, root in enumerate(roots)
        )
    )
    env = {**os.environ, "SB_CONFIG": str(config)}

    def ingest():
        done = subprocess.run(
            [sys.executable, "-m", "sb.cli", "ingest"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert done.returncode == 0, done.stderr + done.stdout

    def snapshot():
        tables = load_ledger_tables(vault / ".sb" / "ledger.db")
        return tuple(tables.source_items.values()), {
            name: value[0] for name, value in tables.cursors.items()
        }

    ingest()
    first, cursors = snapshot()
    assert len(first) == 2
    assert {item.source_id for item in first} == {"agent-0", "agent-1"}
    assert len({item.source_uri for item in first}) == 1
    assert set(cursors) == {"agent-0", "agent-1"}
    compiled = subprocess.run(
        [sys.executable, "-m", "sb.cli", "compile", "--llm", "fake"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr + compiled.stdout
    assert len(list((vault / "wiki").glob("*.md"))) == 2
    pages = {path.name: path.read_bytes() for path in (vault / "wiki").glob("*.md")}
    repeated = subprocess.run(
        [sys.executable, "-m", "sb.cli", "compile", "--llm", "fake"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr + repeated.stdout
    assert {path.name: path.read_bytes() for path in (vault / "wiki").glob("*.md")} == pages
    ingest()
    assert snapshot() == (first, cursors)
    addition = record(kind, "next-id")
    if kind == "gjc":
        addition = addition.split(b"\n", 1)[1]
    with (roots[0] / "session.jsonl").open("ab") as stream:
        stream.write(addition)
    ingest()
    items, after = snapshot()
    assert len(items) == 3
    assert after["agent-1"] == cursors["agent-1"]
    assert after["agent-0"] != cursors["agent-0"]


@pytest.mark.parametrize("kind", list(FACTORIES))
def test_ambiguous_roots_fail_cli_on_every_restart(tmp_path, kind):
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        root.mkdir()
        (root / "session.jsonl").write_bytes(record(kind, "same-id"))
    vault = tmp_path / "vault"
    config = tmp_path / "config.toml"
    config.write_text(
        f'vault_root = "{vault}"\nshare_root = "{tmp_path}"\nstate_root = "{tmp_path / "state"}"\n'
        + "".join(f'[[sources]]\nadapter = "{kind}-sessions"\nroot = "{root}"\n' for root in roots)
    )
    for _ in range(2):
        done = subprocess.run(
            [sys.executable, "-m", "sb.cli", "ingest"],
            env={**os.environ, "SB_CONFIG": str(config)},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert done.returncode != 0
        assert "SOURCE_ROOTS_AMBIGUOUS" in done.stdout + done.stderr
        tables = load_ledger_tables(vault / ".sb" / "ledger.db")
        assert not tables.source_items
        assert not tables.cursors
