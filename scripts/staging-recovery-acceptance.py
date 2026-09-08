"""Actual CLI/MCP recovery after a process exits with unpublished raw staging copies.

TMPDIR=/var/tmp python scripts/staging-recovery-acceptance.py [--provider-root PATH]
Creates and retains an isolated synthetic vault. No operational paths are modified.
"""
from __future__ import annotations

import argparse
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

import anyio
from mcp import StdioServerParameters
from mcp.client import Client


def tree_hash(root: Path) -> str:
    return hashlib.sha256(b"".join(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes()
                                  for path in sorted(root.rglob("*")) if path.is_file())).hexdigest()


def source_hash(repository: Path) -> str:
    return hashlib.sha256(b"".join(str(path.relative_to(repository)).encode() + b"\0"
        + path.read_bytes() + b"\0" for path in sorted((repository / "sb").rglob("*.py")))).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--provider-root", type=Path, default=Path(__file__).resolve().parent.parent)
    repository = cast(Path, parser.parse_args().provider_root).resolve()
    base = Path(mkdtemp(prefix="sb-staging-recovery-"))
    vault = base / "share/vault"
    config = base / "config.toml"
    raw = {"vault_root": str(vault), "share_root": str(base / "share"),
           "state_root": str(base / "state"), "request_root": str(base / "requests"),
           "export_root": str(base / "exports"), "backup_root": str(base / "backups"),
           "knowledge_registry": str(base / "registry.sqlite")}
    text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in raw.items())
    text += ('\n[[sources]]\nid = "inbox"\nadapter = "inbox-documents"\nllm_policy = "allow"\n'
             + '[llm]\nmodel_id = "staging-fixture"\nexternal = false\n'
             + f'argv_template = {json.dumps([sys.executable, str(repository / "scripts/write_cycle_fixture.py")])}\n')
    _ = config.write_text(text)
    env = {**os.environ, "SB_CONFIG": str(config), "SB_MCP_CONTRACT_PROFILE": "remember-schema5",
           "SB_KNOWLEDGE_REGISTRY": raw["knowledge_registry"], "PYTHONPATH": str(repository), "TMPDIR": str(base)}
    evidence: dict[str, object] = {"state": "running", "workspace": str(base), "provider_root": str(repository),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
        "source_hash": source_hash(repository),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["isolated synthetic owner/genesis; deterministic compiler subprocess",
                         "actual process exit and CLI/MCP; not operational restart or physical media erasure"]}

    def save() -> None:
        _ = (base / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))

    def command(arguments: list[str], expected: int = 0) -> str:
        result = subprocess.run(arguments, cwd=repository, env=env, capture_output=True,
                                text=True, timeout=120, check=False)
        with (base / "commands.jsonl").open("a") as output:
            _ = output.write(json.dumps({"args": arguments, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False) + "\n")
        if result.returncode != expected:
            raise RuntimeError("command failed; see native command evidence")
        return result.stdout

    def cli(*arguments: str) -> str:
        return command([sys.executable, "-m", "sb.cli", *arguments])

    async def recall() -> None:
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "sb.mcp"], cwd=repository, env=env)
        async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=60) as client:
            found: list[str] = []
            for marker in ("중단전검증기억", "복구후검증기억"):
                search = await client.call_tool("sb_search", {"query": marker, "limit": 1})
                assert not search.is_error
                payload = cast(dict[str, object], cast(object, search.structured_content))
                rows = cast(list[dict[str, object]], payload["results"])
                assert len(rows) == 1
                page = await client.call_tool("sb_read_page", {"id": rows[0]["page_id"]})
                assert not page.is_error
                body = cast(dict[str, object], cast(object, page.structured_content))
                assert marker in str(body["body"])
                assert all(payload[key] == body[key] for key in ("generation_id", "generation_manifest_digest",
                    "vault_head", "vault_tree", "tombstone_sequence", "tombstone_set_root", "provider_instance_id"))
                records = cast(list[dict[str, object]], body["records"])
                assert any(record["record_id"] == rows[0]["record_id"]
                           and record["record_digest"] == rows[0]["record_digest"]
                           and marker in str(record["record_text"]) for record in records)
                with (base / "mcp.jsonl").open("a") as output:
                    _ = output.write(json.dumps({"marker": marker, "search": payload, "page": body},
                                                ensure_ascii=False) + "\n")
                found.append(marker)
            evidence["recalled"] = found

    print(f"Evidence directory: {base}", flush=True)
    save()
    try:
        _ = cli("init")
        _ = cli("remember", "중단전검증기억 원본은 보존되어야 한다.", "--title", "before-crash")
        _ = cli("ingest")
        _ = cli("compile")
        before = tree_hash(vault.resolve())
        _ = command([sys.executable, "-c", '''
import os
from datetime import UTC, datetime
from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import GenerationAuthority, GenerationMutation, GenerationOperation
service = GenerationMutationService.from_config(load_config())
def crash(root):
 assert any((root / "raw").rglob("*"))
 os._exit(91)
service.mutate(GenerationMutation("actual-staging-crash", GenerationOperation.RUN,
 datetime.now(UTC), GenerationAuthority(None,None), crash))
'''], 91)
        staging = base / "share/vault-generations/.staging"
        stages = tuple(staging.iterdir())
        assert len(stages) == 1
        blobs = [path for path in (stages[0] / "raw").rglob("*") if path.is_file()]
        assert blobs
        evidence.update({"abandoned_stage": stages[0].name, "abandoned_raw_files": len(blobs),
                         "active_unchanged_after_crash": before == tree_hash(vault.resolve())})
        assert evidence["active_unchanged_after_crash"] is True
        cleanup = cast(dict[str, object], json.loads(cli("maintain", "--once")))
        evidence["maintenance"] = cleanup
        evidence["remaining_stages"] = len(tuple(staging.iterdir()))
        save()
        assert cleanup.get("disposed_staging") == 1 and evidence["remaining_stages"] == 0
        assert tree_hash(vault.resolve()) == before
        repeated = cast(dict[str, object], json.loads(cli("maintain", "--once")))
        assert repeated["disposed_staging"] == 0
        _ = cli("remember", "복구후검증기억 새 쓰기도 처리된다.", "--title", "after-recovery")
        _ = cli("ingest")
        _ = cli("compile")
        anyio.run(recall)
        with closing(sqlite3.connect(f"{(vault / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
            assert db.execute("SELECT count(*) FROM source_item").fetchone() == (2,)
        for content in ("중단전검증기억 원본은 보존되어야 한다.", "복구후검증기억 새 쓰기도 처리된다."):
            payload = content.encode()
            digest = hashlib.sha256(payload).hexdigest()
            assert (vault / "raw" / digest[:2] / digest).read_bytes() == payload
        assert source_hash(repository) == evidence["source_hash"]
        evidence.update({"state": "passed", "source_items": 2, "remaining_stages": len(tuple(staging.iterdir())),
                         "cas_originals_exact": True, "product_source_unchanged": True})
    except BaseException as exc:
        evidence.update({"state": "failed", "failure": type(exc).__name__ + ": " + str(exc)})
        raise
    finally:
        evidence["artifact_sha256"] = {name: hashlib.sha256((base / name).read_bytes()).hexdigest()
            for name in ("commands.jsonl", "mcp.jsonl") if (base / name).exists()}
        save()


if __name__ == "__main__":
    main()
