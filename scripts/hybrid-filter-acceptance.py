"""Opt-in native CLI/SQLite filter acceptance with deterministic test embeddings."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from sb.embeddings import vectors_path
from tests.knowledge import commit_page, registry_file
from tests.test_hybrid_filters import seeded

BOOTSTRAP = """from unittest.mock import patch
from tests.test_embeddings import FakeEncoder
from sb.cli import main
with patch('sb.embeddings.resolve_encoder', return_value=FakeEncoder()):
    raise SystemExit(main())
"""


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="sb-hybrid-filter-"))
    with MonkeyPatch.context() as patcher:
        root = seeded(base, patcher)
    config = base / "config.toml"
    prefix = f"vault_root = {json.dumps(str(root))}\nknowledge_registry = {json.dumps(str(registry_file(root)))}\n[search]\n"
    env = {**os.environ, "SB_CONFIG": str(config), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    before = hashlib.sha256(vectors_path(root).read_bytes()).hexdigest()
    results: dict[str, object] = {}

    def cli(label: str, query: str, *options: str) -> list[dict[str, object]]:
        result = subprocess.run([sys.executable, "-c", BOOTSTRAP, "search", query, "--json", *options],
                                env=env, capture_output=True, text=True, check=False, timeout=60)
        _ = (base / f"{label}.stdout").write_text(result.stdout)
        _ = (base / f"{label}.stderr").write_text(result.stderr)
        assert result.returncode == 0 and result.stderr == "", result.stderr
        value = cast(object, json.loads(result.stdout))
        assert isinstance(value, list)
        rows: list[dict[str, object]] = []
        for row in cast(list[object], value):
            assert isinstance(row, dict)
            rows.append(cast(dict[str, object], row))
        results[label] = rows
        return rows

    _ = config.write_text(prefix + "hybrid = false\n")
    options = ("--kind", "wiki", "--status", "active", "--updated-from", "2026-09-08",
               "--updated-to", "2026-09-08", "--limit", "1")
    assert cli("lexical", "SemanticNeedle", *options) == []
    _ = config.write_text(prefix + "hybrid = true\n")
    hits = cli("hybrid", "SemanticNeedle", *options)
    assert len(hits) == 1 and hits[0]["page_id"] == "wiki/z-allowed"
    assert hits[0]["source_ref"] == "origin:wiki/z-allowed"
    assert hits[0]["role"] == "CANONICAL" and hits[0]["verification"] == "VERIFIED"
    candidates = cli("candidate", "absent semantic query", "--scope", "candidate")
    assert len(candidates) == 1 and candidates[0]["page_id"] == "wiki/a-hidden"
    assert cli("literal-filter", "SemanticNeedle", "--status", "active' OR 1=1 --", "--scope", "reference") == []
    commit_page(root, "wiki/z-allowed.md", "---\nstatus: active\nupdated: 2026-09-08\n---\n# Body\nnew corrected value")
    assert cli("corrected", "absent semantic query", *options) == []
    after = hashlib.sha256(vectors_path(root).read_bytes()).hexdigest()
    assert after == before
    report = {"status": "native_cli_filtered_cosine_passed", "root": str(base), "results": results,
              "vector_db_unchanged": True, "encoder": "deterministic fixture; not model quality",
              "sealed_hybrid_acceptance": False, "operational_activation": False}
    _ = (base / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
