"""Source status and conservative CAS retention governance."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from pytest import MonkeyPatch

from sb.cli import main
from sb.config import Config, TomlValue
from sb.contracts import PageSpec, SourceCite
from sb.governance import GovernanceError, collect_orphans, retention_report, source_status
from sb.store import SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault


class _NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _put(root: Path, payload: bytes) -> str:
    return ContentAddressedStore(root).put(payload)


def _run_cli(config_path: Path, argv: list[str]) -> tuple[int, str, str]:
    previous = os.environ.get("SB_CONFIG")
    os.environ["SB_CONFIG"] = str(config_path)
    out, err = StringIO(), StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
    finally:
        if previous is None:
            _ = os.environ.pop("SB_CONFIG", None)
        else:
            os.environ["SB_CONFIG"] = previous
    return code, out.getvalue(), err.getvalue()


def test_source_status_expands_home_and_reports_policy(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source_root = tmp_path / "notes"
    source_root.mkdir()
    config = Config(
        raw=cast(
            dict[str, TomlValue],
            {
                "vault_root": str(tmp_path / "vault"),
                "llm": {"model_id": "remote", "external": True},
                "sources": [
                    {
                        "id": "notes",
                        "adapter": "markdown-vault",
                        "root": "~/notes",
                        "llm_policy": "local-only",
                        "sensitive": "mask",
                    }
                ],
            },
        )
    )

    rows = source_status(config)

    assert len(rows) == 1
    assert rows[0]["id"] == "notes"
    assert rows[0]["root"] == str(source_root)
    assert rows[0]["root_exists"] is True
    assert rows[0]["llm_policy"] == "local-only"
    assert rows[0]["sensitive"] == "mask"


def test_gc_dry_run_and_confirmation_delete_only_verified_orphans(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    orphan = _put(root, b"verified orphan")

    before = collect_orphans(root)
    assert before.orphan_blobs == (orphan,)
    assert (root / "raw" / orphan[:2] / orphan).is_file()

    with pytest.raises(GovernanceError, match="--apply --confirm"):
        _ = collect_orphans(root, apply=True, confirmed=False)
    assert (root / "raw" / orphan[:2] / orphan).is_file()

    after = collect_orphans(root, apply=True, confirmed=True)
    assert after.orphan_blobs == ()
    assert not (root / "raw" / orphan[:2] / orphan).exists()


def test_gc_keeps_ledger_and_page_referenced_blobs(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    vault = init_vault(root)
    ledger_digest = _put(root, b"ledger protected")
    page_digest = _put(root, b"page protected")
    with Ledger(root) as ledger:
        ledger.upsert_source_item(
            SourceItem("notes", "ledger.md", "v1", ledger_digest, "run", "run")
        )
    sid = page_digest[:8]
    result = vault.write_pages(
        [
            PageSpec(
                "protected-page",
                "Protected",
                f"fact.[^{sid}]",
                [SourceCite(sid, "notes:page.md", page_digest)],
                "active",
            )
        ],
        "protected-run",
        _NoPreviousHash(),
    )
    assert result.commit is not None

    report = collect_orphans(root, apply=True, confirmed=True)

    assert report.orphan_blobs == ()
    assert report.protected_blobs == 2
    assert (root / "raw" / ledger_digest[:2] / ledger_digest).is_file()
    assert (root / "raw" / page_digest[:2] / page_digest).is_file()


def test_invalid_cas_file_is_reported_and_never_deleted(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    fake_digest = "a" * 64
    invalid = root / "raw" / fake_digest[:2] / fake_digest
    invalid.parent.mkdir(parents=True, exist_ok=True)
    _ = invalid.write_bytes(b"does not match filename")

    report = collect_orphans(root, apply=True, confirmed=True)

    assert report.invalid_blobs == (f"{fake_digest[:2]}/{fake_digest}",)
    assert invalid.is_file()


def test_gc_refuses_to_run_while_pipeline_lock_is_held(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    _ = _put(root, b"orphan")
    lock = root / ".sb" / "run.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(GovernanceError, match="vault is busy"):
            _ = collect_orphans(root, apply=True, confirmed=True)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_cli_gc_requires_confirmation_and_emits_json(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    orphan = _put(root, b"cli orphan")
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text(f'vault_root = "{root}"\n', encoding="utf-8")

    code, _out, err = _run_cli(config_path, ["gc", "--apply"])
    assert code == 1
    assert "--apply --confirm" in err
    assert (root / "raw" / orphan[:2] / orphan).is_file()

    code, out, err = _run_cli(config_path, ["gc", "--apply", "--confirm", "--json"])
    assert code == 0 and err == ""
    payload = cast(dict[str, object], json.loads(out))
    assert payload["orphan_count"] == 0
    assert not (root / "raw" / orphan[:2] / orphan).exists()


def test_retention_report_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    digest = _put(root, b"read only orphan")
    path = root / "raw" / digest[:2] / digest
    before = path.stat().st_mtime_ns

    report = retention_report(root)

    assert report.orphan_blobs == (digest,)
    assert path.stat().st_mtime_ns == before


def test_retention_reads_sealed_generation_without_mutating_files(tmp_path: Path) -> None:
    import hashlib
    from datetime import UTC, datetime

    from sb.generation_runtime import GenerationMutationService
    from sb.pipeline import run_ingest
    from tests.test_runtime_reliability import managed

    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("봉인 세대의 원본 보존", "보존", datetime.now(UTC))
    finally:
        service.close()
    assert run_ingest(config, ("inbox",)).exit_code == 0
    root = Path(config.vault_root).resolve()

    def snapshot() -> dict[str, tuple[int, int, str]]:
        return {str(path.relative_to(root)): (path.stat().st_mode, path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest())
                for path in root.rglob("*") if path.is_file()}

    before = snapshot()
    report = retention_report(root)
    assert report.raw_blobs == report.protected_blobs == 1
    assert not report.orphan_blobs and not report.invalid_blobs
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text("\n".join(
        f"{key} = {json.dumps(value)}" for key, value in config.raw.items()
        if isinstance(value, str)
    ))
    code, output, error = _run_cli(config_path, ["retention", "--json"])
    assert code == 0 and error == ""
    assert json.loads(output) == report.as_dict()
    assert snapshot() == before


def test_retention_does_not_migrate_legacy_ledger(tmp_path: Path) -> None:
    import sqlite3
    from contextlib import closing

    root = tmp_path / "vault"
    _ = init_vault(root)
    digest = _put(root, b"protected only by legacy source ledger")
    database = root / ".sb/ledger.db"
    with closing(sqlite3.connect(database)) as connection:
        _ = connection.execute("CREATE TABLE source_item (content_hash TEXT)")
        _ = connection.execute("INSERT INTO source_item VALUES (?)", (digest,))
        connection.commit()
    before = database.read_bytes()
    report = retention_report(root)
    assert report.protected_blobs == 1 and not report.orphan_blobs
    assert database.read_bytes() == before


def test_retention_corrupt_ledger_refuses_orphan_deletion(tmp_path: Path) -> None:
    from sb.store import LedgerCorrupt

    root = tmp_path / "vault"
    _ = init_vault(root)
    digest = _put(root, b"must not delete after failed protection lookup")
    _ = (root / ".sb/ledger.db").write_bytes(b"not a sqlite database")
    with pytest.raises(LedgerCorrupt):
        _ = collect_orphans(root, apply=True, confirmed=True)
    assert (root / "raw" / digest[:2] / digest).is_file()


def test_retention_sees_committed_source_hash_in_live_wal(tmp_path: Path) -> None:
    root = tmp_path / "vault with spaces #1"
    _ = init_vault(root)
    digest = _put(root, b"protected by a committed WAL source")
    with Ledger(root) as writer:
        _ = writer.upsert_source_items((SourceItem("wal", "note.md", "1", digest, "r1", "r1"),))
        assert (root / ".sb/ledger.db-wal").stat().st_size > 0
        report = retention_report(root)
        assert report.protected_blobs == 1 and not report.orphan_blobs
