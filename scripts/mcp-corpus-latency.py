"""Measure candidate MCP search p50/p95 on fixed isolated corpora."""
from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import anyio
from mcp import StdioServerParameters
from mcp.client import Client

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.remember_page import materialize_remember
from sb.source_access import SourceAccess

SIZES = (("small", 30), ("medium", 100), ("large", 300))
SAMPLES = 11
NEEDLE = "M11CorpusNeedle unique-span"


def _page_ids(payload: dict[str, object]) -> list[str]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("page_id"), str):
            ids.append(row["page_id"])
    return ids


def _percentile(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * q) - 1]


def _seed(folder: Path, pages: int) -> None:
    now = datetime.now(UTC)
    scope = SourceAccess("principal:owner", ("project:allowed",), "policy:1")
    for number in range(pages):
        extra = NEEDLE if number == 0 else f"filler-{number}"
        materialize_remember(
            folder,
            content=f"CorpusPage {number} {extra}",
            candidate_id="memcand:pos:v1:" + hashlib.sha256(str(number).encode()).hexdigest(),
            created_at=now.isoformat(),
            release_sha="a" * 40,
            source_access=scope,
        )


def _server_rss_kib(client: object) -> int | None:
    session = getattr(client, "_session", None)
    proc = getattr(session, "_proc", None) or getattr(client, "_process", None)
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int):
        return None
    status = Path(f"/proc/{pid}/status")
    if not status.is_file():
        return None
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


def _correct_existing_page(folder: Path, new_text: str) -> str:
    wiki = folder / "wiki"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "sb",
        "GIT_AUTHOR_EMAIL": "sb@local",
        "GIT_COMMITTER_NAME": "sb",
        "GIT_COMMITTER_EMAIL": "sb@local",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    for page in sorted(wiki.glob("*.md")):
        body = page.read_text(encoding="utf-8")
        if NEEDLE not in body:
            continue
        page.write_text(body.replace(NEEDLE, new_text), encoding="utf-8")
        rel = str(page.relative_to(folder))
        subprocess.run(["git", "-C", str(folder), "add", "--", rel], check=True, env=env)
        subprocess.run(["git", "-C", str(folder), "commit", "-m", "correct existing memory", "--no-gpg-sign"],
                       check=True, env=env, capture_output=True, text=True)
        return page.stem
    raise RuntimeError("needle page missing")


async def _search_times(command: str, config: Path, cwd: Path, query: str, samples: int) -> tuple[list[float], dict[str, object], int | None]:
    params = StdioServerParameters(
        command=command, args=[], cwd=str(cwd),
        env={**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    times: list[float] = []
    payload: dict[str, object] = {}
    rss: int | None = None
    async with Client(params, mode="legacy", cache=None, read_timeout_seconds=30) as client:
        rss = _server_rss_kib(client)
        for _ in range(samples):
            started = time.perf_counter()
            result = await client.call_tool("sb_search", {"query": query, "limit": 5})
            elapsed = time.perf_counter() - started
            if result.is_error:
                raise RuntimeError(str(result))
            times.append(elapsed)
            payload = dict(result.structured_content or {})
    return times, payload, rss


async def _concurrent(command: str, config: Path, cwd: Path, query: str) -> list[float]:
    params = StdioServerParameters(
        command=command, args=[], cwd=str(cwd),
        env={**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    times: list[float] = []
    async with Client(params, mode="legacy", cache=None, read_timeout_seconds=30) as client:
        async def one() -> None:
            started = time.perf_counter()
            result = await client.call_tool("sb_search", {"query": query, "limit": 5})
            if result.is_error:
                raise RuntimeError(str(result))
            times.append(time.perf_counter() - started)
        async with anyio.create_task_group() as group:
            group.start_soon(one)
            group.start_soon(one)
    return times


async def _retry(command: str, config: Path, cwd: Path, query: str) -> dict[str, object]:
    env = {**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"}
    lost_params = StdioServerParameters(command=command, args=[], cwd=str(cwd), env=env)
    lost_error = None
    try:
        async with Client(lost_params, mode="legacy", cache=None, read_timeout_seconds=0.001) as client:
            await client.call_tool("sb_search", {"query": query, "limit": 1})
    except (TimeoutError, OSError, ExceptionGroup) as exc:
        lost_error = type(exc).__name__
    started = time.perf_counter()
    ok_params = StdioServerParameters(command=command, args=[], cwd=str(cwd), env=env)
    async with Client(ok_params, mode="legacy", cache=None, read_timeout_seconds=30) as client:
        result = await client.call_tool("sb_search", {"query": query, "limit": 1})
    return {
        "lost_error": lost_error,
        "retry_seconds": round(time.perf_counter() - started, 4),
        "retry_error": result.is_error,
        "retry_hits": len((result.structured_content or {}).get("results") or []),
    }


def _write_config(root: Path) -> Path:
    config = root / "config.toml"
    config.write_text("\n".join([
        f'vault_root = "{root / "share/vault"}"',
        f'share_root = "{root / "share"}"',
        f'state_root = "{root / "state"}"',
        f'request_root = "{root / "requests"}"',
        f'export_root = "{root / "exports"}"',
        'provider_instance_id = "provider:m11-corpus"',
    ]) + "\n")
    return config


def main() -> None:
    release = Path(os.environ["SB_CANDIDATE_RELEASE"]).resolve(strict=True)
    command = str(release / "bin/second-brain-mcp")
    sizes: dict[str, object] = {}
    report: dict[str, object] = {
        "candidate": str(release),
        "samples": SAMPLES,
        "sizes": sizes,
        "live_model": False,
    }
    for label, pages in SIZES:
        root = Path(tempfile.mkdtemp(prefix=f"sb-m11-{label}-", dir="/var/tmp"))
        root.chmod(0o700)
        cfg = Config(raw={
            "vault_root": str(root / "share/vault"),
            "share_root": str(root / "share"),
            "state_root": str(root / "state"),
            "request_root": str(root / "requests"),
            "export_root": str(root / "exports"),
        })
        service = GenerationMutationService.from_config(cfg)
        try:
            service.mutate(GenerationMutation(
                f"m11:{label}", GenerationOperation.REMEMBER, datetime.now(UTC),
                GenerationAuthority(None, None), lambda folder, count=pages: _seed(folder, count),
            ))
            config = _write_config(root)
            times, last, server_rss = anyio.run(_search_times, command, config, root, NEEDLE, SAMPLES)
            hits = _page_ids(last)
            concurrent = anyio.run(_concurrent, command, config, root, NEEDLE)
            retry = anyio.run(_retry, command, config, root, NEEDLE)
            new_needle = f"M11Corrected-{label}"
            def _rewrite(folder: Path, text: str = new_needle) -> None:
                wiki = folder / "wiki"
                for page in sorted(wiki.glob("*.md")):
                    body = page.read_text(encoding="utf-8")
                    if NEEDLE not in body:
                        continue
                    page.write_text(body.replace(NEEDLE, text), encoding="utf-8")
                    return
                raise RuntimeError("needle page missing")
            service.mutate(GenerationMutation(
                f"m11:{label}:correct", GenerationOperation.REMEMBER, datetime.now(UTC),
                GenerationAuthority(None, None), _rewrite,
            ))
            corrected_page = new_needle
            after, after_last, _ = anyio.run(_search_times, command, config, root, new_needle, 1)
            _stale_times, stale_last, _ = anyio.run(_search_times, command, config, root, NEEDLE, 1)
            sizes[label] = {
                "pages": pages,
                "root": str(root),
                "seconds": [round(value, 4) for value in times],
                "p50": round(statistics.median(times), 4),
                "p95": round(_percentile(times, 0.95), 4),
                "max": round(max(times), 4),
                "hits": hits,
                "concurrent_seconds": [round(value, 4) for value in concurrent],
                "retry": retry,
                "correction_of_existing_page": corrected_page,
                "correction_seconds": round(after[0], 4),
                "correction_hits": _page_ids(after_last),
                "stale_needle_hits_after_correction": _page_ids(stale_last),
                "mcp_server_rss_kib": server_rss,
            }
        finally:
            service.close()
    report["client_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out = Path("/var/tmp/m11-mcp-corpus-latency.json")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
