"""Opt-in 100 managed capture/run cycles on the full capacity-plan corpus.

TMPDIR=/var/tmp uv run python scripts/write-cycle-acceptance.py --full
Without --full, run a small three-cycle smoke with 70 existing conflicts.
Always creates an isolated directory and retains native command/MCP evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import cast, final

import anyio
from anyio.abc import TaskStatus
from anyio.to_thread import run_sync
from mcp import StdioServerParameters
from mcp.client import Client

# File-path entry point: the sibling module is placed on sys.path by Python.
from write_cycle_fixture import (  # pyright: ignore[reportImplicitRelativeImport]
    SEED_TERM,
    seed_pages,
    source_text,
)

from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.governance import retention_report
from sb.ops import restore_backup
from sb.runtime_backup import backup_runtime
from sb.search import SearchIndex
from sb.vault import init_vault


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("structured MCP object required")
    return cast(dict[str, object], value)


def size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def percentiles(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    assert ordered
    return {"count": len(ordered), "p50_ms": ordered[math.ceil(len(ordered) * .5) - 1],
            "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1], "max_ms": ordered[-1]}


@final
class Acceptance:
    def __init__(self, full: bool) -> None:
        self.base = Path(mkdtemp(prefix="sb-write-cycles-"))
        self.repository = Path(__file__).resolve().parent.parent
        self.vault = self.base / "share/vault"
        self.config_file = self.base / "config.toml"
        self.source_count, self.page_count, self.conflict_count, self.cycles = (
            (5000, 10000, 1000, 100) if full else (5, 10, 70, 3)
        )
        self.raw: dict[str, str] = {"vault_root": str(self.vault),
            "state_root": str(self.base / "state"), "request_root": str(self.base / "requests"),
            "backup_root": str(self.base / "backups"), "export_root": str(self.base / "exports"),
            "knowledge_registry": str(self.base / "registry.sqlite")}
        self.environment = {**os.environ, "SB_CONFIG": str(self.config_file),
                            "SB_MCP_CONTRACT_PROFILE": "remember-schema5",
                            "SB_KNOWLEDGE_REGISTRY": self.raw["knowledge_registry"],
                            "PYTHONPATH": str(self.repository), "TMPDIR": str(self.base)}
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repository,
                                  text=True, capture_output=True, check=False)
        self.evidence: dict[str, object] = {"state": "running", "full": full,
            "workspace": str(self.base), "started_at": datetime.now(UTC).isoformat(),
            "target_cycles": self.cycles, "completed_cycles": 0,
            "commit": revision.stdout.strip() if revision.returncode == 0 else None,
            "source_tree_sha256": self.source_hash(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "fixture_sha256": hashlib.sha256((self.repository / "scripts/write_cycle_fixture.py").read_bytes()).hexdigest(),
            "limitations": ["synthetic precompiled baseline and deterministic LLM subprocess",
                            "real CLI capture/run and two MCP SDK reader processes; not agent apps",
                            "single owner, no deletes or policy changes in this load scenario",
                            "not Korean relevance, real model throughput or operational deployment"]}
        self.commands: list[dict[str, object]] = []
        self.reads: list[dict[str, object]] = []
        self.growth: list[dict[str, int]] = []
        self.first_page = ""
        self.stop = anyio.Event()
        self.save()

    def source_hash(self) -> str:
        return hashlib.sha256(b"".join(
            str(path.relative_to(self.repository)).encode() + b"\0" + path.read_bytes() + b"\0"
            for path in sorted((self.repository / "sb").rglob("*.py")))).hexdigest()

    def save(self) -> None:
        _ = (self.base / "evidence.json").write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2) + "\n")

    def note(self, key: str, value: object) -> None:
        self.evidence[key] = value
        self.save()
        print(json.dumps({key: value}, ensure_ascii=False), flush=True)

    def configure(self, managed: bool) -> None:
        if managed:
            self.raw["share_root"] = str(self.base / "share")
        text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in self.raw.items())
        text += (f'\n[[sources]]\nid = "baseline"\nadapter = "markdown-vault"\n'
                 f'root = {json.dumps(str(self.base / "sources"))}\nllm_policy = "allow"\n'
                 '[[sources]]\nid = "inbox"\nadapter = "inbox-documents"\nllm_policy = "allow"\n'
                 f'[caps]\nmax_new_units_per_run = {self.source_count * 20}\n'
                 f'max_source_items_per_run = {self.source_count + 1}\n'
                 '[llm]\nmodel_id = "write-cycle-fixture"\nexternal = false\n'
                 f'argv_template = {json.dumps([sys.executable, str(self.repository / "scripts/write_cycle_fixture.py")])}\n')
        _ = self.config_file.write_text(text)

    def cli(self, *arguments: str) -> str:
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-m", "sb.cli", *arguments],
                                env=self.environment, capture_output=True, text=True,
                                cwd=self.repository, timeout=1800, check=False)
        ended = time.monotonic()
        row: dict[str, object] = {"args": list(arguments), "start": started, "end": ended,
            "elapsed_ms": (ended - started) * 1000, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}
        self.commands.append(row)
        with (self.base / "commands.jsonl").open("a") as stream:
            _ = stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if result.returncode or "already running" in result.stdout:
            raise RuntimeError(f"CLI {arguments[0]} did not complete; see commands.jsonl")
        return result.stdout

    def counts(self) -> dict[str, int]:
        with closing(sqlite3.connect(f"{(self.vault / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
            counts = {table: cast(int, db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                      for table in ("source_item", "unit", "run")}
            assert db.execute("SELECT count(*) FROM run WHERE status != 'ok'").fetchone() == (0,)
            assert db.execute("SELECT count(*) FROM derivation WHERE status != 'done'").fetchone() == (0,)
            return counts

    def prepare(self) -> None:
        print(f"Evidence directory: {self.base}", flush=True)
        (self.base / "sources").mkdir()
        for index in range(self.source_count):
            _ = (self.base / "sources" / f"source-{index:05d}.md").write_text(source_text(index))
        self.configure(False)
        _ = init_vault(self.vault)
        _ = self.cli("ingest", "--source", "baseline")
        self.first_page = seed_pages(load_config(self.config_file), self.page_count, self.conflict_count)
        self.configure(True)
        service = GenerationMutationService.from_config(load_config(self.config_file))
        try:
            _ = service.mutate(GenerationMutation("write-load:genesis", GenerationOperation.RUN,
                datetime.now(UTC), GenerationAuthority(None, None), lambda _root: None))
        finally:
            service.close()
        initial = self.counts()
        assert initial["source_item"] == self.source_count and initial["unit"] == self.source_count * 20
        self.note("baseline", {**initial, "pages": self.page_count, "conflicts": self.conflict_count,
                               "active_bytes": size(self.vault.resolve()), "disk_free": shutil.disk_usage(self.base).free})

    def parameters(self) -> StdioServerParameters:
        return StdioServerParameters(command=sys.executable, args=["-m", "sb.mcp"],
                                     env=self.environment, cwd=self.repository)

    async def call(self, client: Client, name: str, method: str, arguments: dict[str, object]) -> dict[str, object]:
        started = time.monotonic()
        result = await client.call_tool(method, arguments)
        ended = time.monotonic()
        row: dict[str, object] = {"client": name, "method": method, "arguments": arguments,
            "start": started, "end": ended, "elapsed_ms": (ended - started) * 1000,
            "is_error": result.is_error, "response": cast(object, result.structured_content),
            "error": str(result.content) if result.is_error else None}
        with (self.base / "mcp.jsonl").open("a") as stream:
            _ = stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        # Retain full native evidence on disk, only timing metadata in memory.
        self.reads.append({key: row[key] for key in ("client", "method", "start", "end", "elapsed_ms")})
        if result.is_error:
            raise RuntimeError(f"MCP {method} failed: {result.content}")
        payload = object_value(cast(object, result.structured_content))
        assert all(field in payload for field in ("generation_id", "generation_manifest_digest",
                   "vault_head", "vault_tree", "tombstone_sequence", "tombstone_set_root", "provider_instance_id"))
        assert payload["tombstone_sequence"] == 0
        return payload

    async def reader(self, name: str, *, task_status: TaskStatus[None]) -> None:
        async with Client(self.parameters(), mode="legacy", cache=None, read_timeout_seconds=60) as client:
            task_status.started()
            while not self.stop.is_set():
                search = await self.call(client, name, "sb_search", {"query": SEED_TERM, "limit": 1})
                assert search.get("results")
                read = await self.call(client, name, "sb_read_page", {"id": self.first_page})
                assert SEED_TERM in str(read.get("body"))
                records = read.get("records")
                assert isinstance(records, list) and len(cast(list[object], records)) == 1
                assert SEED_TERM in str(object_value(cast(list[object], records)[0]).get("record_text"))

    async def run_cycles(self) -> None:
        async with (
            Client(self.parameters(), mode="legacy", cache=None, read_timeout_seconds=60) as observer,
            anyio.create_task_group() as tasks,
        ):
            await tasks.start(self.reader, "reader-a")
            await tasks.start(self.reader, "reader-b")
            try:
                for number in range(1, self.cycles + 1):
                    marker = f"반복실측기억{number:04d}"
                    content = f"{marker} 확인값 {hashlib.sha256(marker.encode()).hexdigest()}"
                    _ = await run_sync(self.cli, "remember", content, "--title", marker)
                    _ = await run_sync(self.cli, "run")
                    search = await self.call(observer, "observer", "sb_search", {"query": marker, "limit": 10})
                    hits = search.get("results")
                    assert isinstance(hits, list) and hits
                    hit = object_value(cast(list[object], hits)[0])
                    page = await self.call(observer, "observer", "sb_read_page", {"id": hit["page_id"]})
                    assert content in str(page.get("body"))
                    assert search["generation_id"] == page["generation_id"]
                    assert any(object_value(row).get("record_id") == hit.get("record_id")
                               and object_value(row).get("record_digest") == hit.get("record_digest")
                               for row in cast(list[object], page["records"]))
                    # A scheduled run also publishes the daily page; it must be
                    # consumable by the same schema5 interface as wiki memories.
                    for daily in sorted((self.vault / "daily").glob("*.md")):
                        _ = await self.call(observer, "observer", "sb_read_page", {"id": f"daily/{daily.stem}"})
                    counts = self.counts()
                    assert counts["source_item"] == self.source_count + number
                    assert counts["unit"] == self.source_count * 20 + number
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    assert (self.vault / "raw" / digest[:2] / digest).read_bytes() == content.encode()
                    self.note("completed_cycles", number)
                    if number % 10 == 0 or number == self.cycles:
                        self.growth.append({"cycle": number, "active_bytes": size(self.vault.resolve()),
                                            "workspace_bytes": size(self.base)})
                        self.note("growth", self.growth)
            finally:
                self.stop.set()
        runs = [row for row in self.commands if row["args"] == ["run"]]
        overlap = [sum(cast(float, row["start"]) >= cast(float, run["start"]) and cast(float, row["end"]) <= cast(float, run["end"])
                       for row in self.reads if row["client"] != "observer") for run in runs]
        assert len(runs) == self.cycles and all(overlap), overlap
        self.note("concurrent_reads_per_run", overlap)
        for method in ("sb_search", "sb_read_page"):
            self.note(method, percentiles([cast(float, row["elapsed_ms"]) for row in self.reads
                                          if row["method"] == method and row["client"] != "observer"]))
        self.note("run_latency", percentiles([cast(float, row["elapsed_ms"]) for row in runs]))
        self.note("capture_latency", percentiles([cast(float, row["elapsed_ms"]) for row in self.commands
                                                  if cast(list[str], row["args"])[0] == "remember"]))

    def finish(self) -> None:
        before = self.counts()
        _ = self.cli("run")
        after = self.counts()
        assert after["source_item"] == before["source_item"] and after["unit"] == before["unit"]
        retention = retention_report(self.vault)
        assert retention.raw_blobs == self.source_count + self.cycles
        assert not retention.orphan_blobs and not retention.invalid_blobs
        archive = self.base / "backups/final.tar.gz"
        backup = backup_runtime(load_config(self.config_file), archive)
        restored = self.base / "restored"
        _ = restore_backup(archive, restored)
        for number in range(1, self.cycles + 1):
            query = f"반복실측기억{number:04d}"
            original = SearchIndex(self.vault).search(query, 10)
            assert original and original == SearchIndex(restored).search(query, 10)
        assert retention_report(restored) == retention
        assert self.source_hash() == self.evidence["source_tree_sha256"], "provider source changed during acceptance"
        self.note("final", {**after, "same_cas_audit": True, "restored_recalls": self.cycles,
                            "unchanged_replay": True, "backup_bytes": archive.stat().st_size,
                            "backup_checksum": backup.checksum, "retention": retention.as_dict()})
        self.note("state", "passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    acceptance = Acceptance(cast(bool, args.full))
    try:
        acceptance.prepare()
        anyio.run(acceptance.run_cycles)
        acceptance.finish()
    except BaseException as exc:
        acceptance.note("failure", {"type": type(exc).__name__, "message": str(exc)})
        acceptance.note("state", "failed")
        raise


if __name__ == "__main__":
    main()
