"""Profile real CLI writes against a private copy of a completed synthetic load fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pstats
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import cast


def product_hash(repository: Path) -> str:
    return hashlib.sha256(b"".join(str(p.relative_to(repository)).encode() + b"\0"
        + p.read_bytes() + b"\0" for p in sorted((repository / "sb").rglob("*.py")))).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    source = cast(Path, args.fixture).resolve()
    evidence = cast(dict[str, object], json.loads((source / "evidence.json").read_text()))
    if (evidence.get("state") != "passed" or evidence.get("full") is not True
        or evidence.get("workspace") != str(source)
        or not source.name.startswith("sb-write-cycles-") or not (source / "sources").is_dir()):
        raise ValueError("expected a completed synthetic full write-cycle fixture")
    base = Path(tempfile.mkdtemp(prefix="sb-write-profile-"))
    repository = Path(__file__).resolve().parents[1]
    initial_hash = product_hash(repository)
    print(f"Profile directory: {base}", flush=True)
    for name in ("share", "state", "requests"):
        _ = shutil.copytree(source / name, base / name, symlinks=True)
    if (source / "registry.sqlite").is_file():
        _ = shutil.copyfile(source / "registry.sqlite", base / "registry.sqlite")
    # Preserve baseline source origins/cursors; the source connector only reads them.
    config = (source / "config.toml").read_text().replace(str(source), str(base))
    config = config.replace(str(base / "sources"), str(source / "sources"))
    path = base / "config.toml"
    _ = path.write_text(config)
    env = dict(os.environ, SB_CONFIG=str(path), PYTHONPATH=str(repository), TMPDIR=str(base))
    marker = "쓰기프로파일기억"
    commands: list[dict[str, object]] = []
    for label, arguments in (("remember", ["remember", marker + " 확인값 profile-value", "--title", marker]),
                              ("run", ["run"])):
        profile = base / (label + ".pstats")
        start = time.perf_counter()
        done = subprocess.run([sys.executable, "-m", "cProfile", "-o", str(profile),
                               "-m", "sb.cli", *arguments], env=env, cwd=repository,
                              capture_output=True, text=True, check=False, timeout=1800)
        elapsed = time.perf_counter() - start
        _ = (base / (label + ".stdout")).write_text(done.stdout)
        _ = (base / (label + ".stderr")).write_text(done.stderr)
        with (base / (label + "-profile.txt")).open("w") as output:
            _ = pstats.Stats(str(profile), stream=output).sort_stats("cumulative").print_stats(60)
        row: dict[str, object] = {"command": label, "seconds": elapsed, "exit": done.returncode}
        commands.append(row)
        print(json.dumps(row), flush=True)
        if done.returncode:
            raise RuntimeError(f"profiled {label} failed; see {base}")
    query = subprocess.run([sys.executable, "-m", "sb.cli", "search", marker, "--json"],
                           env=env, cwd=repository, capture_output=True, text=True, check=False)
    if query.returncode or "profile-value" not in query.stdout:
        raise RuntimeError("profiled memory was not retrieved")
    _ = (base / "search.json").write_text(query.stdout)
    db = sqlite3.connect((base / "share/vault/.sb/ledger.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        counts = {table: cast(tuple[int], db.execute(f"SELECT count(*) FROM {table}").fetchone())[0]
                  for table in ("source_item", "unit")}
    finally:
        db.close()
    if product_hash(repository) != initial_hash:
        raise RuntimeError("product source changed during profiling")
    final = evidence.get("final")
    if not isinstance(final, dict):
        raise TypeError("fixture final counts missing")
    for name, count in counts.items():
        original = cast(dict[str, object], final).get(name)
        if not isinstance(original, int) or count != original + 1:
            raise RuntimeError("profiled source/unit counts differ from one new memory")
    report = {"state": "passed", "source_fixture": str(source), "workspace": str(base),
              "source_tree_sha256": initial_hash, "commands": commands, "counts": counts,
              "limitations": ["deterministic LLM fixture", "cProfile overhead included",
                              "no concurrent reader load; compare matched profiles only"]}
    _ = (base / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
