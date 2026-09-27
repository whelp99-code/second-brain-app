"""Behavioral reproductions of the Task 30 independent-verifier findings."""

from __future__ import annotations

import gc
import secrets
import shutil
import subprocess
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from mcp.client import Client

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.effect_values import format_instant
from sb.effect_write_requests import accept_effect_request
from sb.generations import scan_open_generation_descriptors
from sb.llm import LLMClient, LLMUnavailable
from sb.managed_copy_disposal import copy_inventory
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_surface_scan import scan_managed_surfaces
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.memory_records import parse_page_records
from sb.pipeline import StageReport, run_brief, run_compile
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault
from sb.write_request_values import digest as write_digest
from tests.task30_effect_factory import effect_request
from tests.task30_process_harness import NOW, executor_config


def test_reopened_brief_releases_readers_without_gc(tmp_path: Path) -> None:
    # Given: the real pipeline retries a failed brief while GC cannot close readers.
    root = init_vault(tmp_path / "share/vault").root
    config = Config(raw={"vault_root": str(root), "share_root": str(root.parent),
        "state_root": str(tmp_path / "state"), "request_root": str(tmp_path / "requests"),
        "export_root": str(tmp_path / "exports"), "backup_root": str(tmp_path / "backups")})
    digest = ContentAddressedStore(root).put(b"synthetic briefing source")
    cite = SourceCite(digest[:8], "inbox:brief.md", digest)
    calls = 0
    def brief(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        nonlocal calls
        del inputs, llm, config
        calls += 1
        if calls == 1:
            raise LLMUnavailable(attempts=1, reason="synthetic failure")
        return PageSpec("daily/reopened", "Reopened", f"current [^{cite.sid}]", [cite], "active")
    def empty(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 0, 0, False)
    enabled = gc.isenabled()
    gc.disable()
    try:
        assert run_brief(config, generator=brief).exit_code == 1
        assert run_brief(config, generator=brief).exit_code == 0
        predecessor = root.resolve()
        # When: the next publication drains the generation containing the reopened brief.
        outcome = run_compile(config, compiler=empty)
        # Then: no leaked SQLite reader holds the disposed generation.
        assert outcome.exit_code == 0
        assert scan_open_generation_descriptors((predecessor,)) == 0
        assert not predecessor.exists()
    finally:
        if enabled:
            gc.enable()
        _ = gc.collect()


def test_legacy_recent_changes_observes_v1_generation(tmp_path: Path) -> None:
    # Given: the V1 write path publishes a sealed root commit at the actual activation time.
    config = executor_config(tmp_path)
    with closing(RequestExecutor(config)) as executor:
        now = datetime.now(UTC)
        request = write_fixture_request()
        request["created_at"] = format_instant(now)
        request["expires_at"] = format_instant(now + timedelta(days=1))
        receipt = request["receipt"]
        assert isinstance(receipt, dict)
        receipt["issued_at"], receipt["expires_at"] = request["created_at"], request["expires_at"]
        request["receipt_digest"] = write_digest("receipt", receipt)
        del request["request_id"], request["request_digest"]
        digest = write_digest("request", request)
        request.update(request_id="memreq:pos:v1:" + digest[7:], request_digest=digest)
        _ = accept_stable_v1_request(config.request_root, request, now)
        assert executor.apply_once(now=now).state == "proved"
        current = executor.generations.active()
        page_id = "wiki/" + next((current.root / "wiki").glob("memory-*.md")).stem
        runtime = Config(raw={"vault_root": str(executor.generations.active_link),
            "share_root": str(config.share_root), "state_root": str(config.state_root),
            "request_root": str(config.request_root), "export_root": str(config.export_root),
            "backup_root": str(config.backup_root), "provider_instance_id": config.provider_instance_id})
        async def read_recent() -> bool:
            async with Client(build_server(config=runtime, task30=False), mode="legacy", cache=None) as client:
                result = await client.call_tool("sb_recent_changes", {"days": 7})
                assert not result.is_error
                return page_id in result.model_dump_json()
        # When: an unchanged Task29 client reads recent changes.
        observed = anyio.run(read_recent)
        # Then: the V1-visible page is recent despite the deterministic root commit date.
        assert observed


def test_backup_git_objects_are_disposed_without_plaintext_match(tmp_path: Path) -> None:
    # Given: a renamed bare Git backup with only compressed retained content.
    needle = secrets.token_hex(32).encode() * 8
    source = tmp_path / "source"
    source.mkdir()
    _ = subprocess.run(["git", "init", "-q", str(source)], check=True)
    _ = subprocess.run(["git", "-C", str(source), "hash-object", "-w", "--stdin"],
                   input=needle, check=True, capture_output=True)
    backups = tmp_path / "backups"
    backups.mkdir()
    retained = backups / "retained.git"
    _ = shutil.copytree(source / ".git", retained)
    assert all(needle not in path.read_bytes() for path in retained.rglob("*") if path.is_file())
    # When: the managed erasure boundary purges and inventories backup copies.
    _ = purge_matching_managed_copies((backups,), (needle,))
    _ = copy_inventory((backups,), (needle,))
    # Then: decompressed objects cannot survive a clean receipt.
    assert not retained.exists()
    inventory = scan_managed_surfaces((backups,), (needle,))
    assert inventory.matches == 0 and inventory.scan_errors == 0


def test_correction_reconstructs_marker_inside_task30_span(tmp_path: Path) -> None:
    # Given: a Task30 selector includes the citation marker in its exact record span.
    config = executor_config(tmp_path)
    with closing(RequestExecutor(config)) as executor:
        _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
        assert executor.apply_once(now=NOW).state == "proved"
        generation = executor.generations.active()
        page = next((generation.root / "wiki").glob("memory-*.md"))
        records = parse_page_records(page.read_bytes(), page.stem)
        assert len(records) == 1
        prior = records[0]
        raw = page.read_bytes()
        marker = f"[^{prior.sid}]".encode()
        end = raw.index(marker, prior.citation_span_end) + len(marker)
        cited = raw[prior.citation_span_start:end].decode()
        replacement = secrets.token_hex(24)
        request = effect_request(generation, "correct", cited, NOW,
            executor.store.tombstone_high_water(), config.provider_signing_key, "8",
            correction_content=replacement)
        _ = accept_effect_request(config.request_root, request, NOW,
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
        # When: the signed correction supersedes the complete cited span.
        result = executor.apply_once(now=NOW)
        # Then: the successor has the same exact citation and none of the old statement.
        assert result.state == "proved"
        raw = (executor.generations.active().root / page.relative_to(generation.root)).read_bytes()
        corrected = parse_page_records(raw, page.stem)
        assert len(corrected) == 1
        assert [(row.record_text, row.sid) for row in corrected] == [(replacement, prior.sid)]
        assert prior.record_text.encode() not in raw
