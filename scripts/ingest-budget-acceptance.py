"""Real managed CLI acceptance for unit limits and retained source retries.

TMPDIR=/var/tmp uv run python scripts/ingest-budget-acceptance.py
Creates and retains only a new isolated directory; no LLM or operational writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import mkdtemp
from typing import cast


def source(label: str, units: int) -> bytes:
    return "\n\n".join(" ".join([f"{label}항목{i}"] + ["a"] * 598) + "."
                       for i in range(units)).encode()


def main() -> None:
    base = Path(mkdtemp(prefix="sb-ingest-budget-acceptance-"))
    vault = base / "share/vault"
    config = base / "config.toml"
    print(f"Evidence directory: {base}", flush=True)
    environment = {**os.environ, "SB_CONFIG": str(config)}
    commands: list[dict[str, object]] = []

    def configure(units: int) -> None:
        paths = {"vault_root": vault, "share_root": base / "share", "state_root": base / "state",
                 "request_root": base / "requests", "export_root": base / "exports",
                 "knowledge_registry": base / "registry.sqlite"}
        _ = config.write_text("\n".join(f"{key} = {json.dumps(str(value))}"
                                       for key, value in paths.items())
                              + '\n[[sources]]\nid = "inbox"\nadapter = "inbox-documents"\n'
                              + f'\n[caps]\nmax_new_units_per_run = {units}\nmax_source_items_per_run = 10\n')

    def command(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, "-m", "sb.cli", *args], env=environment,
                                capture_output=True, text=True, check=False, timeout=120)
        commands.append({"args": args, "exit_code": result.returncode, "stdout": result.stdout,
                         "stderr": result.stderr, "config": config.read_text()})
        _ = (base / "commands.json").write_text(json.dumps(commands, ensure_ascii=False, indent=2))
        assert result.returncode == expected, result
        return result

    def inspect(items: int, units: int, status: str) -> None:
        with closing(sqlite3.connect(f"{(vault / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
            assert db.execute("SELECT count(*) FROM source_item").fetchone() == (items,)
            assert db.execute("SELECT count(*) FROM unit").fetchone() == (units,)
            assert db.execute("SELECT status FROM run_stage ORDER BY rowid DESC LIMIT 1").fetchone() == (status,)

    originals = {"a-big.md": source("big", 20), "b-small.md": source("small", 1)}
    configure(1)
    _ = command("init")
    paths: dict[str, Path] = {}
    for name, data in originals.items():
        captured = command("remember", data.decode(), "--title", name)
        paths[name] = Path(captured.stdout.strip())
    failed = command("ingest", "--source", "inbox", "--limit", "100", expected=1)
    assert "INGEST_UNIT_BUDGET_EXCEEDED" in failed.stderr
    inspect(1, 1, "failed")
    assert vault.is_symlink()
    assert (vault / paths["a-big.md"]).read_bytes() == originals["a-big.md"]
    assert not (vault / paths["b-small.md"]).exists()
    configure(20)
    _ = command("ingest", "--source", "inbox")
    inspect(2, 21, "ok")
    assert not (vault / paths["a-big.md"]).exists()
    for name, count in (("a-wave.md", 12), ("b-wave.md", 12), ("c-wave.md", 8)):
        originals[name] = source(name, count)
        captured = command("remember", originals[name].decode(), "--title", name)
        paths[name] = Path(captured.stdout.strip())
    _ = command("ingest", "--source", "inbox")
    inspect(4, 41, "capped")
    assert (vault / paths["b-wave.md"]).read_bytes() == originals["b-wave.md"]
    assert not (vault / paths["c-wave.md"]).exists()
    _ = command("ingest", "--source", "inbox")
    inspect(5, 53, "ok")
    configure(1)
    _ = command("ingest", "--source", "inbox")
    inspect(5, 53, "ok")
    for data in originals.values():
        digest = hashlib.sha256(data).hexdigest()
        assert (vault / "raw" / digest[:2] / digest).read_bytes() == data
    retention = command("retention", "--json")
    report = cast(dict[str, object], json.loads(retention.stdout))
    assert report["protected_blobs"] == 5 and report["orphan_count"] == report["invalid_count"] == 0
    result = {"state": "passed", "workspace": str(base), "source_items": 5, "units": 53,
              "oversized_source_retained": True, "residual_source_retried": True,
              "same_cas_bytes": True, "replay_added_units": 0,
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    _ = (base / "evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
