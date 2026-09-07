"""Opt-in structural load acceptance; synthetic sources, real CLI/storage/read paths.

Run with TMPDIR=/var/tmp uv run python scripts/capacity-acceptance.py --full.
Artifacts are retained in a newly created directory; never accepts an existing vault.
LLM generation/semantic conflict detection and 100 write cycles are not measured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, final

from sb.config import Config
from sb.contracts import Blob, PageSpec, SourceCite
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.governance import retention_report
from sb.normalize import normalize
from sb.ops import restore_backup
from sb.runtime_backup import backup_runtime
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

TERM = "용량검증공통키워드"


class NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def source_text(index: int) -> str:
    # 20 distinct 600-token paragraphs: 20 real normalizer units, below file/scan caps.
    return "\n\n".join(
        " ".join([f"원본{index:05d}항목{part:02d}"] + ["a"] * 598) + "."
        for part in range(20)
    )


def counts(root: Path) -> dict[str, int]:
    with closing(sqlite3.connect(f"{(root / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
        return {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("source_item", "unit", "run")}


def size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def percentile(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {"count": len(values), "p50_ms": ordered[math.ceil(len(values) * .5) - 1],
            "p95_ms": ordered[math.ceil(len(values) * .95) - 1], "max_ms": ordered[-1]}


@final
class Acceptance:
    def __init__(self, full: bool) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sb-capacity-"))
        self.vault = self.root / "share/vault"
        self.sources = self.root / "sources"
        self.source_count, self.page_count, self.conflict_count, self.repeats = (
            (5000, 10000, 1000, 100) if full else (5, 10, 2, 3)
        )
        self.config_file = self.root / "config.toml"
        self.raw = {"vault_root": str(self.vault), "state_root": str(self.root / "state"),
                    "request_root": str(self.root / "requests"),
                    "export_root": str(self.root / "exports"),
                    "backup_root": str(self.root / "backups"),
                    "knowledge_registry": str(self.vault / ".sb/knowledge-registry.sqlite")}
        self.evidence: dict[str, object] = {
            "schema_version": 1, "state": "running", "full": full,
            "started_at": datetime.now(UTC).isoformat(), "workspace": str(self.root),
            "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "load_average_before": os.getloadavg(),
            "disk_available_before": shutil.disk_usage(self.root).free,
            "implementation_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True).strip(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_tree_sha256": hashlib.sha256(b"".join(
                str(path.relative_to(Path(__file__).resolve().parent.parent)).encode()
                + b"\0" + path.read_bytes() + b"\0"
                for path in sorted((Path(__file__).resolve().parent.parent / "sb").rglob("*.py"))
            )).hexdigest(),
            "limitations": ["synthetic source text and cited page/conflict fixtures",
                            "no LLM throughput or retrieval relevance claim",
                            "repeated reads are not 100 scheduled write cycles",
                            "isolated vault; no operational activation or app acceptance"],
        }
        self.save()

    def save(self) -> None:
        _ = (self.root / "evidence.json").write_text(
            json.dumps(self.evidence, ensure_ascii=False, indent=2) + "\n")

    def note(self, key: str, value: object) -> None:
        self.evidence[key] = value
        self.save()
        print(json.dumps({key: value}, ensure_ascii=False), flush=True)

    def config(self, managed: bool = False) -> Config:
        if managed:
            self.raw["share_root"] = str(self.root / "share")
        content = "\n".join(f"{key} = {json.dumps(value)}" for key, value in self.raw.items())
        content += (f'\n[[sources]]\nid = "capacity"\nadapter = "markdown-vault"\n'
                    f'root = {json.dumps(str(self.sources))}\n')
        content += (f'\n[caps]\nmax_new_units_per_run = {self.source_count * 20}\n'
                    f'max_source_items_per_run = {self.source_count}\n')
        _ = self.config_file.write_text(content)
        return Config(raw=self.raw)

    def cli(self, *arguments: str) -> tuple[str, float]:
        env = {**os.environ, "SB_CONFIG": str(self.config_file),
               "SB_KNOWLEDGE_REGISTRY": self.raw["knowledge_registry"]}
        start = time.perf_counter()
        result = subprocess.run([sys.executable, "-m", "sb.cli", *arguments],
                                capture_output=True, text=True, env=env, timeout=1800, check=False)
        elapsed = (time.perf_counter() - start) * 1000
        with (self.root / "commands.jsonl").open("a") as log:
            _ = log.write(json.dumps({"args": arguments, "exit_code": result.returncode,
                                  "elapsed_ms": elapsed, "stdout": result.stdout,
                                  "stderr": result.stderr}, ensure_ascii=False) + "\n")
        if result.returncode:
            raise RuntimeError(f"CLI {arguments} failed ({result.returncode}); see commands.jsonl")
        return result.stdout, elapsed

    def run(self) -> None:
        print(f"Evidence directory: {self.root}", flush=True)
        self.sources.mkdir()
        _ = self.config()
        _ = init_vault(self.vault)
        digests: list[str] = []
        started = time.perf_counter()
        for index in range(self.source_count):
            data = source_text(index).encode()
            digest = hashlib.sha256(data).hexdigest()
            if index in {0, self.source_count - 1}:
                assert len(normalize(Blob(digest, len(data)), data.decode(), "capacity:fixture")) == 20
            _ = (self.sources / f"source-{index:05d}.md").write_bytes(data)
            digests.append(digest)
        self.note("fixture_sources", {"files": len(digests), "bytes": size(self.sources),
                                      "seconds": time.perf_counter() - started})
        _, ingest_ms = self.cli("ingest", "--source", "capacity", "--limit", str(self.source_count))
        ingested = counts(self.vault)
        assert ingested["source_item"] == self.source_count, ingested
        assert ingested["unit"] == self.source_count * 20, ingested
        self.note("ingest", {**ingested, "elapsed_ms": ingest_ms})
        _, replay_ms = self.cli("ingest", "--source", "capacity", "--limit", str(self.source_count))
        replayed = counts(self.vault)
        assert replayed == {**ingested, "run": ingested["run"] + 1}, replayed
        with Ledger(self.vault) as ledger:
            items = ledger.list_source_items()
            assert {item.content_hash for item in items} == set(digests)
        self.note("unchanged_ingest", {**replayed, "elapsed_ms": replay_ms})
        pages: list[PageSpec] = []
        for index in range(self.page_count + self.conflict_count):
            conflict = index >= self.page_count
            number = index - self.page_count if conflict else index
            digest = digests[index % self.source_count]
            sid = digest[:8]
            page_id = f"{'conflicts' if conflict else 'wiki'}/capacity-{number:05d}"
            pages.append(PageSpec(page_id, f"용량 항목 {number:05d}",
                                  f"# 항목 {number:05d}\n{TERM} 번호 {number:05d}.[^{sid}]",
                                  [SourceCite(sid, f"capacity:source-{index % self.source_count:05d}.md", digest)],
                                  "conflicted" if conflict else "active"))
        started = time.perf_counter()
        result = Vault(self.vault).write_pages(pages, "capacity-fixture", NoPreviousHash())
        assert result.pages == self.page_count and result.conflicts == self.conflict_count
        self.note("committed_fixture", {"pages": result.pages, "conflicts": result.conflicts,
                                       "commit": result.commit,
                                       "elapsed_ms": (time.perf_counter() - started) * 1000})
        config = self.config(managed=True)
        started = time.perf_counter()
        service = GenerationMutationService.from_config(config)
        try:
            generation = service.mutate(GenerationMutation(
                mutation_id="capacity:seal", operation=GenerationOperation.RUN,
                now=datetime.now(UTC), authority=GenerationAuthority(None, None),
                apply=lambda root: None)).generation
        finally:
            service.close()
        assert self.vault.is_symlink()
        self.note("sealed_generation", {"id": generation.generation_id,
                                        "elapsed_ms": (time.perf_counter() - started) * 1000,
                                        "bytes": size(self.vault.resolve())})
        self.measure_reads()
        started = time.perf_counter()
        retained = retention_report(self.vault)
        assert retained.raw_blobs == self.source_count and retained.protected_blobs == self.source_count
        assert not retained.orphan_blobs and not retained.invalid_blobs
        self.note("retention", {**retained.as_dict(), "elapsed_ms": (time.perf_counter() - started) * 1000})
        started = time.perf_counter()
        archive = self.root / "backups/capacity.tar.gz"
        backup = backup_runtime(config, archive)
        self.note("backup", {"files": backup.files, "input_bytes": backup.bytes,
                             "archive_bytes": archive.stat().st_size, "checksum": backup.checksum,
                             "elapsed_ms": (time.perf_counter() - started) * 1000})
        started = time.perf_counter()
        restored = self.root / "restored"
        _ = restore_backup(archive, restored)
        assert counts(restored) == counts(self.vault)
        original_hits = SearchIndex(self.vault).search(TERM, 25)
        restored_hits = SearchIndex(restored).search(TERM, 25)
        assert restored_hits == original_hits
        restored_retention = retention_report(restored)
        assert restored_retention == retained
        assert (restored / ".recovery/requests/journal.db").is_file()
        self.note("restore", {"elapsed_ms": (time.perf_counter() - started) * 1000,
                              "same_search": True, "same_ledger_counts": True,
                              "same_cas_audit": True, "bytes": size(restored)})
        self.note("disk_available_after", shutil.disk_usage(self.root).free)
        self.note("state", "passed")

    def measure_reads(self) -> None:
        index_path = self.vault / ".sb/search.db"
        digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
        timings: list[float] = []
        index = SearchIndex(self.vault)
        for _ in range(self.repeats):
            start = time.perf_counter()
            hits = index.search(TERM, 25, kinds=("wiki",), status="active")
            timings.append((time.perf_counter() - start) * 1000)
            assert len(hits) == min(25, self.page_count)
        self.note("sealed_search_in_process", percentile(timings))
        cli_timings: list[float] = []
        for number in range(self.repeats):
            output, elapsed = self.cli("search", TERM, "--kind", "wiki", "--status", "active",
                                       "--limit", "25", "--json")
            result = cast(list[dict[str, object]], json.loads(output))
            assert len(result) == min(25, self.page_count), result
            cli_timings.append(elapsed)
            if (number + 1) % 10 == 0:
                print(f"Completed {number + 1}/{self.repeats} CLI reads", flush=True)
        assert hashlib.sha256(index_path.read_bytes()).hexdigest() == digest
        self.note("sealed_search_cli", {**percentile(cli_timings), "index_unchanged": True})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--full", action="store_true", help="5k sources/100k units/10k pages/1k conflicts/100 reads")
    args = parser.parse_args()
    acceptance = Acceptance(cast(bool, args.full))
    try:
        acceptance.run()
    except BaseException as exc:
        acceptance.note("failure", {"type": type(exc).__name__, "message": str(exc)})
        acceptance.note("state", "failed")
        raise


if __name__ == "__main__":
    main()
