"""Configured session originals -> K2 receipts -> committed search across restarts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb.config import Config, load_config
from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef
from sb.pipeline import run_compile, run_ingest
from sb.search import SearchIndex
from sb.source_coverage import list_scan_receipts
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault
from tests.test_session_file_replacement import FACTORIES

KINDS = ("claude", "codex", "omo")


def session_bytes(kind: str, text: str) -> bytes:
    match kind:
        case "claude":
            rows = [{"type": "message", "id": "message-1", "text": text}]
        case "codex":
            rows = [
                {"type": "session_meta", "payload": {"id": "session-1"}},
                {"type": "response_item", "payload": {
                    "type": "message", "id": "message-1", "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }},
            ]
        case "omo":
            rows = [{"type": "message", "id": "message-1", "message": {
                "content": [{"type": "text", "text": text}],
            }}]
        case _:
            raise ValueError("unknown session family")
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


def configured(tmp_path: Path, kind: str) -> tuple[Config, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    _ = init_vault(tmp_path / "vault")
    file = tmp_path / "config.toml"
    _ = file.write_text(
        f'vault_root = "{tmp_path / "vault"}"\n'
        + f'knowledge_registry = "{tmp_path / "registry.db"}"\n'
        + f'state_root = "{tmp_path / "state"}"\n'
        + '[llm]\nmodel_id = "local"\nargv_template = ["/bin/false"]\n'
        + f'[[sources]]\nid = "{kind}"\nadapter = "{kind}-sessions"\n'
        + f'root = "{source}"\nllm_policy = "deny"\ndeletion_observations = "v1"\n'
        + f'[source_access.{kind}]\nowner = "principal:owner"\n'
        + 'projects = ["project:session-hardening"]\npolicy_revision = "1"\n',
        encoding="utf-8",
    )
    return load_config(file), source, file


def ingest(file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sb.cli", "ingest"],
        env={**os.environ, "SB_CONFIG": str(file)},
        capture_output=True, text=True, timeout=30, check=False,
    )


@pytest.mark.parametrize("kind", KINDS)
def test_normal_restart_edit_disappearance_receipts_and_search(tmp_path: Path, kind: str) -> None:
    config, source, file = configured(tmp_path, kind)
    page = source / "session.jsonl"
    old_text = "SBSTEP2 oldword"
    new_text = "SBSTEP2 newword"
    original = session_bytes(kind, old_text)
    _ = page.write_bytes(original)
    assert ingest(file).returncode == 0
    assert ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    stamp = page.stat()
    updated = session_bytes(kind, new_text)
    assert len(original) == len(updated)
    _ = page.write_bytes(updated)
    os.utime(page, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    _ = page.rename(tmp_path / "owner-retained.jsonl")
    assert ingest(file).returncode == 0

    with Ledger(config.vault_root) as ledger:
        receipts = list_scan_receipts(ledger, kind)
        assert sum(receipt.accepted for receipt in receipts) == 2
        assert receipts[-1].accepted == 0 and receipts[-1].filtered == 1
        assert receipts[-1].checkpoint_after == ledger.get_cursor(kind)
        items = ledger.list_source_items()
        assert len(items) == 3
        assert sum(item.source_version.startswith("source-deleted:") for item in items) == 1
    cas = ContentAddressedStore(config.vault_root)
    assert cas.get(hashlib.sha256(old_text.encode()).hexdigest()) == old_text.encode()
    assert cas.get(hashlib.sha256(new_text.encode()).hexdigest()) == new_text.encode()
    hits = SearchIndex(Path(config.vault_root)).search("newword", scope="all")
    assert hits and len({hit.page_id for hit in hits}) == 1
    assert (tmp_path / "owner-retained.jsonl").read_bytes() == updated
    assert ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        assert len(ledger.list_source_items()) == 3
        assert list_scan_receipts(ledger, kind)[-1].filtered == 0


@pytest.mark.parametrize("kind", KINDS)
def test_missing_root_preserves_checkpoint_and_corrupt_original(tmp_path: Path, kind: str) -> None:
    config, source, file = configured(tmp_path, kind)
    _ = (source / "session.jsonl").write_bytes(session_bytes(kind, "SBSTEP2 memory"))
    corrupt = b"\xff\xfe\n"
    _ = (source / "bad.jsonl").write_bytes(corrupt)
    assert ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        checkpoint = ledger.get_cursor(kind)
        assert list_scan_receipts(ledger, kind)[-1].quarantined == 1
    _ = source.rename(tmp_path / "offline")

    unavailable = ingest(file)

    assert unavailable.returncode == 1
    with Ledger(config.vault_root) as ledger:
        receipt = list_scan_receipts(ledger, kind)[-1]
        assert receipt.state == "unavailable" and receipt.scanned == 0
        assert receipt.checkpoint_before == receipt.checkpoint_after == checkpoint
        assert ledger.get_cursor(kind) == checkpoint
    _ = (tmp_path / "offline").rename(source)
    assert ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    assert len(SearchIndex(Path(config.vault_root)).search("SBSTEP2", scope="all")) == 1
    assert (source / "bad.jsonl").read_bytes() == corrupt


@pytest.mark.parametrize("kind", KINDS)
def test_incomplete_tail_reports_partial_and_recovers_without_duplicates(
    tmp_path: Path, kind: str,
) -> None:
    config, source, file = configured(tmp_path, kind)
    page = source / "session.jsonl"
    full = session_bytes(kind, "SBSTEP2 completed")
    _ = page.write_bytes(full[:-5])

    partial = ingest(file)

    assert partial.returncode == 1
    with Ledger(config.vault_root) as ledger:
        assert ledger.get_cursor(kind) is None
        receipt = list_scan_receipts(ledger, kind)[-1]
        assert receipt.state == "partial" and receipt.retryable_errors == 1
    _ = page.write_bytes(full)
    assert ingest(file).returncode == 0
    assert ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        assert len(ledger.list_source_items()) == 1
        assert sum(receipt.accepted for receipt in list_scan_receipts(ledger, kind)) == 1
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    assert len(SearchIndex(Path(config.vault_root)).search("SBSTEP2", scope="all")) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_ancestor_swap_cannot_read_outside_selected_root(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    page = nested / "session.jsonl"
    _ = page.write_bytes(session_bytes(kind, "permitted"))
    outside = tmp_path / "outside"
    outside.mkdir()
    _ = (outside / "session.jsonl").write_bytes(
        session_bytes(kind, "FORBIDDEN_OUTSIDE_ALLOWLIST")
    )

    def swap_paths(root: Path) -> list[Path]:
        assert root == source
        _ = nested.rename(tmp_path / "retained")
        nested.symlink_to(outside, target_is_directory=True)
        return [page]

    monkeypatch.setattr(f"sb.connectors.sessions_{kind}._jsonl_paths", swap_paths)
    adapter = FACTORIES[kind]((source,), kind)
    rows: list[tuple[SourceRef, bytes, ItemMeta]] = list(adapter.scan(None))
    assert not any(b"FORBIDDEN_OUTSIDE_ALLOWLIST" in body for _ref, body, _meta in rows)
    assert any(meta.get("skip_reason") == "unreadable-session-file" for _ref, _body, meta in rows)


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_offset_revision_is_not_duplicated_by_content_version_upgrade(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, source, _file = configured(tmp_path, kind)
    page = source / "session.jsonl"
    original = session_bytes(kind, "SBSTEP2 existing memory")
    _ = page.write_bytes(original)
    reader = FACTORIES[kind]((source,), kind)

    class LegacyReader:
        source_id: str = kind
        accepted_adapters: frozenset[str] = frozenset({kind + "-sessions"})

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
            for ref, body, meta in reader.scan(cursor):
                offset = meta.get("cursor")
                assert isinstance(offset, str)
                yield SourceRef(ref.source_id, ref.source_uri, offset), body, meta

        def next_cursor(self) -> str:
            return reader.next_cursor()

    def legacy_discovery(_config: Config) -> dict[str, SourceAdapter]:
        return {kind: LegacyReader()}

    with monkeypatch.context() as old:
        old.setattr("sb.connectors.discover_adapters", legacy_discovery)
        assert run_ingest(config, (kind,)).exit_code == 0
    with Ledger(config.vault_root) as ledger:
        assert ledger.list_source_items()[0].source_version.isdecimal()
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    # Rewrite JSON whitespace without changing the already accepted message.
    _ = page.write_bytes(original.rstrip(b"\n") + b" \n")
    assert run_ingest(config, (kind,)).exit_code == 0

    with Ledger(config.vault_root) as ledger:
        assert len(ledger.list_source_items()) == 1
        receipts = list_scan_receipts(ledger, kind)
        assert sum(receipt.accepted for receipt in receipts) == 1
        assert receipts[-1].unchanged == 1
    assert len(SearchIndex(Path(config.vault_root)).search("SBSTEP2", scope="all")) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_disappearance_defaults_off_and_rollback_preserves_known_checkpoint(
    tmp_path: Path, kind: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    page = source / "session.jsonl"
    _ = page.write_bytes(session_bytes(kind, "SBSTEP2 retained"))
    reader = FACTORIES[kind]((source,), kind)
    assert list(reader.scan(None))
    cursor = reader.next_cursor()
    _ = page.rename(tmp_path / "retained.jsonl")

    assert list(reader.scan(cursor)) == []
    assert reader.next_cursor() == cursor


@pytest.mark.parametrize("kind", KINDS)
def test_incomplete_other_file_is_not_disappearance_evidence(tmp_path: Path, kind: str) -> None:
    config, source, file = configured(tmp_path, kind)
    page = source / "session.jsonl"
    _ = page.write_bytes(session_bytes(kind, "SBSTEP2 retained"))
    assert ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        checkpoint = ledger.get_cursor(kind)
    _ = page.rename(tmp_path / "retained.jsonl")
    _ = (source / "pending.jsonl").write_bytes(session_bytes(kind, "SBSTEP2 partial")[:-5])

    assert ingest(file).returncode == 1

    with Ledger(config.vault_root) as ledger:
        assert ledger.get_cursor(kind) == checkpoint
        assert not any(
            item.source_version.startswith("source-deleted:") for item in ledger.list_source_items()
        )
    assert (tmp_path / "retained.jsonl").exists()
