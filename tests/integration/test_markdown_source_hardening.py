"""Real configured Markdown ingest, restart, scan receipts and committed search."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sb.config import Config, load_config
from sb.governance import source_status
from sb.pipeline import run_compile
from sb.search import SearchIndex
from sb.source_coverage import list_scan_receipts
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault


def configured(tmp_path: Path) -> tuple[Config, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    _ = init_vault(tmp_path / "vault")
    file = tmp_path / "config.toml"
    _ = file.write_text(
        f'vault_root = "{tmp_path / "vault"}"\n'
        + f'knowledge_registry = "{tmp_path / "registry.db"}"\n'
        + f'state_root = "{tmp_path / "state"}"\n'
        + '[llm]\nmodel_id = "local"\nargv_template = ["/bin/false"]\n'
        + '[[sources]]\nid = "notes"\nadapter = "markdown-vault"\n'
        + f'root = "{source}"\nllm_policy = "deny"\ndeletion_observations = "v1"\n'
        + '[source_access.notes]\nowner = "principal:owner"\n'
        + 'projects = ["project:source-hardening"]\npolicy_revision = "1"\n',
        encoding="utf-8",
    )
    return load_config(file), source, file


def _ingest(file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sb.cli", "ingest", *args],
        env={**os.environ, "SB_CONFIG": str(file)},
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_capped_restart_retains_receipts_and_search_without_duplicates(tmp_path: Path) -> None:
    config, source, file = configured(tmp_path)
    _ = (source / "a.md").write_text("# SBSTEP1\nfirst accepted note\n")
    _ = (source / "b.md").write_text("# SBSTEP1\nsecond retained note\n")

    capped = _ingest(file, "--limit", "1")
    assert capped.returncode == 0, capped.stdout + capped.stderr
    with Ledger(config.vault_root) as ledger:
        assert ledger.get_cursor("notes") is None
        before = list_scan_receipts(ledger, "notes")
        assert before[-1].state == "partial"
        assert before[-1].accepted == 1
    resumed = _ingest(file)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    repeated = _ingest(file)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert run_compile(config, llm_mode="subprocess").exit_code == 0

    with Ledger(config.vault_root) as ledger:
        items = ledger.list_source_items()
        assert len(items) == 2
        receipts = list_scan_receipts(ledger, "notes")
        assert sum(item.accepted for item in receipts) == 2
        assert receipts[-1].accepted == 0
        assert ledger.get_cursor("notes") == receipts[-1].checkpoint_after
    hits = SearchIndex(Path(config.vault_root)).search("SBSTEP1", scope="all")
    assert len(hits) == 2
    assert (source / "a.md").read_text() == "# SBSTEP1\nfirst accepted note\n"
    assert (source / "b.md").read_text() == "# SBSTEP1\nsecond retained note\n"


def test_same_mtime_update_and_disappearance_preserve_searchable_originals(tmp_path: Path) -> None:
    config, source, file = configured(tmp_path)
    page = source / "a.md"
    original = b"# SBSTEP1\noldword\n"
    _ = page.write_bytes(original)
    stamp = page.stat()
    assert _ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    updated = b"# SBSTEP1\nnewword\n"
    _ = page.write_bytes(updated)
    os.utime(page, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    assert _ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    _ = page.rename(tmp_path / "owner-retained.md")
    assert _ingest(file).returncode == 0

    with Ledger(config.vault_root) as ledger:
        rows = [item for item in ledger.list_source_items() if item.source_uri == "a.md"]
        assert len(rows) == 3
        receipts = list_scan_receipts(ledger, "notes")
        assert receipts[-1].filtered == 1
        assert receipts[-1].accepted == 0
    cas = ContentAddressedStore(config.vault_root)
    assert cas.get(hashlib.sha256(original).hexdigest()) == original
    assert cas.get(hashlib.sha256(updated).hexdigest()) == updated
    assert (tmp_path / "owner-retained.md").read_bytes() == updated
    assert SearchIndex(Path(config.vault_root)).search("newword", scope="all")


def test_corrupt_markdown_is_quarantined_and_offline_scan_retains_checkpoint(tmp_path: Path) -> None:
    config, source, file = configured(tmp_path)
    _ = (source / "bad.md").write_bytes(b"\xff\xfe SBSTEP1")
    _ = (source / "ok.md").write_text("# SBSTEP1\nsafe accepted memory\n")

    assert _ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        receipt = list_scan_receipts(ledger, "notes")[-1]
        checkpoint = ledger.get_cursor("notes")
        assert receipt.quarantined == 1
        assert receipt.accepted == 1
        assert receipt.scanned == 2
    _ = source.rename(tmp_path / "offline")
    offline = _ingest(file)
    assert offline.returncode == 1
    with Ledger(config.vault_root) as ledger:
        last = list_scan_receipts(ledger, "notes")[-1]
        assert last.state == "unavailable"
        assert last.scanned == last.retryable_errors == 0
        assert ledger.get_cursor("notes") == checkpoint
        assert last.checkpoint_before == last.checkpoint_after == checkpoint
    _ = (tmp_path / "offline").rename(source)
    assert _ingest(file).returncode == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    assert len(SearchIndex(Path(config.vault_root)).search("SBSTEP1", scope="all")) == 1
    coverage = source_status(config)[0]["coverage"]
    assert coverage["accepted"] == 1
    last_scan = coverage["last_scan"]
    assert last_scan is not None and last_scan["accepted"] == 0
    assert (source / "bad.md").read_bytes() == b"\xff\xfe SBSTEP1"


@pytest.mark.parametrize("filename", [None, "tab\tand\nnewline.md"])
def test_empty_or_opaque_filename_cursor_is_not_an_unavailable_source(
    tmp_path: Path, filename: str | None,
) -> None:
    config, source, file = configured(tmp_path)
    if filename is not None:
        _ = (source / filename).write_text("# SBSTEP1\nopaque filename\n")

    first = _ingest(file)

    assert first.returncode == 0, first.stdout + first.stderr
    with Ledger(config.vault_root) as ledger:
        receipt = list_scan_receipts(ledger, "notes")[-1]
        assert receipt.state == "ok"
        assert receipt.checkpoint_after == ledger.get_cursor("notes")


def test_incomplete_scan_does_not_publish_deletion_candidates(tmp_path: Path) -> None:
    config, source, file = configured(tmp_path)
    page = source / "a.md"
    _ = page.write_text("# SBSTEP1\nretained\n")
    assert _ingest(file).returncode == 0
    with Ledger(config.vault_root) as ledger:
        checkpoint = ledger.get_cursor("notes")
    _ = page.rename(tmp_path / "retained.md")
    unsafe = source / "unsafe.md"
    _ = unsafe.write_text("untrusted writable file\n")
    unsafe.chmod(0o666)

    failed = _ingest(file)

    assert failed.returncode == 1
    with Ledger(config.vault_root) as ledger:
        assert ledger.get_cursor("notes") == checkpoint
        assert not any(
            item.source_version.startswith("source-deleted:") for item in ledger.list_source_items()
        )
        assert list_scan_receipts(ledger, "notes")[-1].state == "unavailable"
    assert (tmp_path / "retained.md").read_text() == "# SBSTEP1\nretained\n"
