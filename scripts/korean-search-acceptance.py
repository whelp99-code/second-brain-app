"""Measure fixed Korean gold queries through actual CLI and schema-5 stdio MCP.

TMPDIR=/var/tmp uv run python scripts/korean-search-acceptance.py [--dataset FILE]
Seeds cited fixture pages using Vault; does not evaluate ingestion or LLM answers.
Quality misses are measurements. Transport, evidence and fixture errors fail the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
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
from anyio.to_thread import run_sync
from korean_search_evaluation import (  # pyright: ignore[reportImplicitRelativeImport]
    Case,
    array,
    load_dataset,
    object_value,
    string,
    summarize,
)
from mcp import StdioServerParameters
from mcp.client import Client

from sb.config import load_config
from sb.contracts import PageSpec, SourceCite
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.knowledge_registry import KnowledgeRegistry
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

BINDINGS = ("provider_instance_id", "generation_id", "generation_manifest_digest",
            "vault_head", "vault_tree", "tombstone_sequence", "tombstone_set_root")


class NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def tree_hash(root: Path, pattern: str) -> str:
    return hashlib.sha256(b"".join(str(path.relative_to(root)).encode() + b"\0"
        + path.read_bytes() + b"\0" for path in sorted(root.rglob(pattern)) if path.is_file())).hexdigest()


def latency(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {"count": len(values), "p50_ms": ordered[math.ceil(len(values) * .5) - 1],
            "p95_ms": ordered[math.ceil(len(values) * .95) - 1], "max_ms": ordered[-1]}


@final
class Evaluation:
    def __init__(self, path: Path, *, hybrid: bool = False) -> None:
        self.hybrid = hybrid
        self.dataset_bytes = path.read_bytes()
        self.dataset = load_dataset(cast(object, json.loads(self.dataset_bytes)))
        self.base = Path(mkdtemp(prefix="sb-korean-search-"))
        self.repository = Path(__file__).resolve().parent.parent
        self.vault = self.base / "share/vault"
        self.config_file = self.base / "config.toml"
        self.environment = {**os.environ, "SB_CONFIG": str(self.config_file),
            "SB_MCP_CONTRACT_PROFILE": "remember-schema5", "PYTHONPATH": str(self.repository),
            "SB_KNOWLEDGE_REGISTRY": str(self.base / "registry.sqlite"), "TMPDIR": str(self.base)}
        self.documents = {doc.page_id: doc for doc in self.dataset.documents}
        self.rankings: dict[str, dict[str, list[str]]] = {"cli": {}, "mcp": {}}
        self.timings: dict[str, list[float]] = {"cli_search": [], "mcp_search": [], "mcp_read": []}
        self.binding: dict[str, object] | None = None
        self.read_checks = 0
        self.answer_checks = 0
        self.evidence: dict[str, object] = {"state": "running", "workspace": str(self.base),
            "started_at": datetime.now(UTC).isoformat(), "dataset_id": self.dataset.id,
            "dataset_origin": self.dataset.origin, "provenance": self.dataset.provenance,
            "dataset_sha256": hashlib.sha256(self.dataset_bytes).hexdigest(),
            "source_tree_sha256": tree_hash(self.repository / "sb", "*.py"),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metrics_sha256": hashlib.sha256((self.repository / "scripts/korean_search_evaluation.py").read_bytes()).hexdigest(),
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repository, text=True).strip(),
            "python": sys.version, "platform": platform.platform(), "load_average_before": os.getloadavg(),
            "documents": len(self.dataset.documents), "cases": len(self.dataset.cases), "limit": 5,
            "limitations": ["isolated cited fixture pages; no ingestion, extraction or LLM answer evaluation",
                            "single trusted owner at genesis; no scope, supersession or deletion test",
                            "SDK stdio MCP, not agent app injection; hybrid " + str(hybrid),
                            "synthetic data cannot replace the real-user 100–300 question acceptance",
                            "small corpus, one pass; latency is diagnostic, not capacity certification"]}
        _ = (self.base / "dataset.json").write_bytes(self.dataset_bytes)

    def save(self) -> None:
        _ = (self.base / "evidence.json").write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2) + "\n")

    def append(self, filename: str, row: dict[str, object]) -> None:
        with (self.base / filename).open("a") as stream:
            _ = stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def prepare(self) -> None:
        raw = {"vault_root": str(self.vault), "share_root": str(self.base / "share"),
               "state_root": str(self.base / "state"), "request_root": str(self.base / "requests"),
               "backup_root": str(self.base / "backups"), "export_root": str(self.base / "exports"),
               "knowledge_registry": self.environment["SB_KNOWLEDGE_REGISTRY"]}
        _ = self.config_file.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in raw.items())
                                        + "\n[search]\nhybrid = " + str(self.hybrid).lower() + "\n")
        vault = init_vault(self.vault)
        cas = ContentAddressedStore(self.vault)
        registry = KnowledgeRegistry(Path(raw["knowledge_registry"]))
        pages: list[PageSpec] = []
        for doc in self.dataset.documents:
            digest = cas.put(doc.body.encode())
            origin = "korean-evaluation:" + doc.page_id
            pages.append(PageSpec(doc.page_id, doc.title, doc.body + f"[^{digest[:8]}]",
                                  [SourceCite(digest[:8], origin, digest)], "active"))
            _ = registry.put(doc.page_id, knowledge_status="ACTIVE", approval_status="APPROVED",
                             decided_by="evaluation-fixture", reason="isolated gold corpus")
        written = vault.write_pages(pages, "korean-evaluation-fixture", NoPreviousHash())
        if written.pages != len(pages) or written.proposals:
            raise ValueError("fixture page publication incomplete")
        service = GenerationMutationService.from_config(load_config(self.config_file))
        try:
            _ = service.mutate(GenerationMutation("korean-evaluation:genesis", GenerationOperation.RUN,
                datetime.now(UTC), GenerationAuthority(None, None), lambda _root: None))
        finally:
            service.close()
        if self.hybrid:
            with closing(sqlite3.connect((self.vault.resolve() / ".sb/vectors.db").as_uri() + "?mode=ro", uri=True)) as conn:
                enabled, count = cast(tuple[int, int], conn.execute(
                    "SELECT enabled,row_count FROM generation_meta").fetchone())
                if enabled != 1 or count != len(self.documents):
                    raise ValueError("real hybrid evaluation requires enabled cited vectors for every document")
                self.evidence["embedding"] = dict(zip(("model_id", "revision", "dim", "row_count", "rows_digest"),
                    cast(tuple[object, ...], conn.execute("SELECT * FROM vector_info").fetchone()), strict=True))
        self.evidence["vault_before"] = tree_hash(self.vault.resolve(), "*")

    async def call(self, client: Client, case: Case, method: str,
                   arguments: dict[str, object]) -> dict[str, object]:
        start = time.perf_counter()
        result = await client.call_tool(method, arguments)
        elapsed = (time.perf_counter() - start) * 1000
        payload = cast(object, result.structured_content)
        self.append("mcp.jsonl", {"case_id": case.id, "method": method, "arguments": arguments,
                    "elapsed_ms": elapsed, "is_error": result.is_error, "response": payload,
                    "error": str(result.content) if result.is_error else None})
        if result.is_error:
            raise ValueError(f"MCP {method} tool error; see native evidence")
        response = object_value(payload)
        binding = {key: response[key] for key in BINDINGS}
        if binding["tombstone_sequence"] != 0 or (self.binding is not None and self.binding != binding):
            raise ValueError("generation changed or non-genesis response")
        self.binding = binding
        self.timings["mcp_search" if method == "sb_search" else "mcp_read"].append(elapsed)
        return response

    def cli(self, case: Case) -> list[str]:
        start = time.perf_counter()
        result = subprocess.run([sys.executable, "-m", "sb.cli", "search", case.query, "--json", "--limit", "5"],
            cwd=self.repository, env=self.environment, capture_output=True, text=True, timeout=60, check=False)
        elapsed = (time.perf_counter() - start) * 1000
        self.append("cli.jsonl", {"case_id": case.id, "query": case.query, "elapsed_ms": elapsed,
                    "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise ValueError("CLI search failed; see native evidence")
        if self.hybrid and "using lexical results" in result.stderr:
            raise ValueError("hybrid encoder failed during CLI measurement; see native evidence")
        rows = array(cast(object, json.loads(result.stdout)))
        self.timings["cli_search"].append(elapsed)
        return [string(object_value(row).get("page_id")) for row in rows]

    async def evaluate(self) -> None:
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "sb.mcp"],
                                           cwd=self.repository, env=self.environment)
        async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=60) as client:
            for number, case in enumerate(self.dataset.cases, 1):
                cli_pages = await run_sync(self.cli, case)
                search = await self.call(client, case, "sb_search", {"query": case.query, "limit": 5})
                hits = [object_value(value) for value in array(search.get("results"))]
                mcp_pages = [string(hit.get("page_id")) for hit in hits]
                for pages in (cli_pages, mcp_pages):
                    if len(pages) > 5 or any(page not in self.documents for page in pages):
                        raise ValueError("result limit or corpus identity violated")
                for page_id in dict.fromkeys(mcp_pages):
                    page = await self.call(client, case, "sb_read_page", {"id": page_id})
                    body = string(page.get("body"))
                    records = [object_value(value) for value in array(page.get("records"))]
                    expected_origin = hashlib.sha256(("korean-evaluation:" + page_id).encode()).hexdigest()
                    for hit in (hit for hit in hits if hit["page_id"] == page_id):
                        record_id, digest = string(hit.get("record_id")), string(hit.get("record_digest"))
                        matched = [r for r in records if r.get("record_id") == record_id and r.get("record_digest") == digest]
                        if len(matched) != 1 or matched[0].get("source_identity_full") != expected_origin:
                            raise ValueError("selected record or source identity missing from read")
                        record_text = string(matched[0].get("record_text"))
                        if record_text not in body or self.documents[page_id].body not in body:
                            raise ValueError("fixture body or selected record lost")
                        if page_id in case.expected:
                            if case.answer_span is None or case.answer_span not in record_text:
                                raise ValueError("gold answer absent from selected record")
                            self.answer_checks += 1
                        self.read_checks += 1
                self.rankings["cli"][case.id] = cli_pages
                self.rankings["mcp"][case.id] = mcp_pages
                self.append("rankings.jsonl", {"case_id": case.id, "kind": case.kind,
                    "expected": case.expected, "cli": cli_pages, "mcp": mcp_pages})
                if number % 20 == 0:
                    self.evidence["completed_cases"] = number
                    self.save()
                    print(f"Completed {number}/{len(self.dataset.cases)} cases", flush=True)

    async def run(self) -> None:
        print(f"Evidence directory: {self.base}", flush=True)
        self.save()
        try:
            self.prepare()
            await self.evaluate()
            if self.evidence["source_tree_sha256"] != tree_hash(self.repository / "sb", "*.py"):
                raise ValueError("product source changed during evaluation")
            for key, path in (("harness_sha256", Path(__file__)),
                              ("metrics_sha256", self.repository / "scripts/korean_search_evaluation.py")):
                if self.evidence[key] != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise ValueError("evaluation code changed during measurement")
            if self.evidence["vault_before"] != tree_hash(self.vault.resolve(), "*"):
                raise ValueError("sealed fixture files changed during reads")
            self.evidence.update({"state": "measured", "completed_cases": len(self.dataset.cases),
                "metrics": {surface: summarize(self.dataset.cases, rows) for surface, rows in self.rankings.items()},
                "latency": {name: latency(rows) for name, rows in self.timings.items() if rows},
                "generation": self.binding, "selected_record_checks": self.read_checks,
                "gold_answer_checks": self.answer_checks, "sealed_files_unchanged": True,
                "finished_at": datetime.now(UTC).isoformat()})
        except BaseException as exc:
            self.evidence.update({"state": "failed", "failure": type(exc).__name__ + ": " + str(exc)})
            raise
        finally:
            self.evidence["artifact_sha256"] = {name: hashlib.sha256((self.base / name).read_bytes()).hexdigest()
                for name in ("dataset.json", "cli.jsonl", "mcp.jsonl", "rankings.jsonl") if (self.base / name).exists()}
            self.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--dataset", type=Path,
                            default=Path(__file__).resolve().parent.parent / "tests/fixtures/korean_search_v1.json")
    _ = parser.add_argument("--hybrid", action="store_true", help="require real enabled generation vectors")
    args = parser.parse_args()
    evaluation = Evaluation(cast(Path, args.dataset), hybrid=cast(bool, args.hybrid))
    anyio.run(evaluation.run)


if __name__ == "__main__":
    main()
