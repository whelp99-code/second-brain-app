"""SQLite ingest ledger: WAL, K2 tables, derivation machine, rebuild, corrupt fail-fast."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from sb.store import (
    DerivationOutput,
    InvalidDerivationTransition,
    LedgerCorrupt,
    SourceItem,
    UnitRow,
    deriv_key,
    format_file_cursor,
    format_jsonl_cursor,
    format_postgres_cursor,
)
from sb.store.ledger import Ledger, rebuild_from_vault

_UNIT_A: str = "unit-a"
_UNIT_B: str = "unit-b"
_STAGE: str = "compile"
_PROMPT: str = "v1"
_MODEL: str = "fake"
# Independent known-good of the documented NUL-joined encoding.
_DERIV_GOLDEN: str = hashlib.sha256(b"u1\x00compile\x00v1\x00fake").hexdigest()


def _table_columns(db_path: Path, table: str) -> list[str]:
    completed = subprocess.run(
        ["sqlite3", str(db_path), f"PRAGMA table_info({table});"],
        capture_output=True,
        text=True,
        check=True,
    )
    names: list[str] = []
    for line in completed.stdout.splitlines():
        fields = line.split("|")
        if len(fields) >= 2:
            names.append(fields[1])
    return names


def test_open_ledger_creates_wal_file_and_reports_wal_mode(tmp_path: Path) -> None:
    """Given a vault, when the ledger opens, then journal_mode is wal."""
    with Ledger(tmp_path) as ledger:
        mode = ledger.journal_mode()

    assert mode == "wal"


def test_open_ledger_creates_k2_tables_with_architect_columns(tmp_path: Path) -> None:
    """Given a new vault, when the ledger opens, then K2 tables exist with exact columns."""
    with Ledger(tmp_path):
        pass
    db_path = tmp_path / ".sb" / "ledger.db"

    assert _table_columns(db_path, "source_item") == [
        "source_id",
        "source_uri",
        "source_version",
        "content_hash",
        "first_seen_run",
        "last_seen_run",
    ]
    assert _table_columns(db_path, "cursor") == ["source_id", "position", "updated_at"]
    assert _table_columns(db_path, "unit") == [
        "unit_id",
        "content_hash",
        "span",
        "text_hash",
        "normalizer_version",
    ]
    assert _table_columns(db_path, "derivation") == [
        "deriv_key",
        "stage",
        "output_hash",
        "output_path",
        "status",
        "attempts",
        "error",
        "run_id",
        "finished_at",
    ]
    assert _table_columns(db_path, "run") == [
        "run_id",
        "started_at",
        "finished_at",
        "git_commit",
        "status",
    ]


def test_open_raises_ledger_corrupt_when_db_bytes_are_garbage(tmp_path: Path) -> None:
    """Given a truncated ledger file, when open runs, then LedgerCorrupt is raised."""
    db_path = tmp_path / ".sb" / "ledger.db"
    db_path.parent.mkdir(parents=True)
    with Ledger(tmp_path) as ledger:
        _ = ledger.journal_mode()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    _ = db_path.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(LedgerCorrupt):
        Ledger(tmp_path).open()


def test_cursor_roundtrip_stores_k2_file_postgres_and_jsonl_positions(tmp_path: Path) -> None:
    """Given K2 cursor encodings, when they are stored, then get_cursor returns each verbatim."""
    file_pos = format_file_cursor(mtime_ns=111, size=222, sha256="ab" * 32)
    pg_pos = format_postgres_cursor("2026-08-25T07:00:00+00:00")
    jsonl_pos = format_jsonl_cursor(4096)

    with Ledger(tmp_path) as ledger:
        ledger.set_cursor("me-wiki", file_pos, "2026-08-25T07:00:00+00:00")
        ledger.set_cursor("unified-db", pg_pos, "2026-08-25T07:00:01+00:00")
        ledger.set_cursor("omo-sessions", jsonl_pos, "2026-08-25T07:00:02+00:00")

        assert file_pos == f"111:222:{'ab' * 32}"
        assert pg_pos == "2026-08-25T07:00:00+00:00"
        assert jsonl_pos == "4096"
        assert ledger.get_cursor("me-wiki") == file_pos
        assert ledger.get_cursor("unified-db") == pg_pos
        assert ledger.get_cursor("omo-sessions") == jsonl_pos


def test_deriv_key_is_stable_and_independent_of_unit_id_order() -> None:
    """Given the same inputs shuffled, when deriv_key runs, then the digest is identical."""
    left = deriv_key((_UNIT_B, _UNIT_A), _STAGE, _PROMPT, _MODEL)
    right = deriv_key((_UNIT_A, _UNIT_B), _STAGE, _PROMPT, _MODEL)

    assert left == right
    assert len(left) == 64


def test_deriv_key_changes_when_stage_or_prompt_changes() -> None:
    """Given a baseline key, when stage or prompt_version changes, then the digest changes."""
    baseline = deriv_key((_UNIT_A,), _STAGE, _PROMPT, _MODEL)

    assert baseline != deriv_key((_UNIT_A,), "conflict", _PROMPT, _MODEL)
    assert baseline != deriv_key((_UNIT_A,), _STAGE, "v2", _MODEL)
    assert baseline != deriv_key((_UNIT_A,), _STAGE, _PROMPT, "other")


def test_deriv_key_matches_documented_nul_joined_encoding() -> None:
    """Given the fixture inputs, when deriv_key runs, then it matches the documented encoding."""
    digest = deriv_key(("u1",), "compile", "v1", "fake")

    assert digest == _DERIV_GOLDEN


def test_derivation_transitions_pending_to_running_to_done(tmp_path: Path) -> None:
    """Given a pending row, when it is marked running then done, then status is done."""
    key = deriv_key((_UNIT_A,), _STAGE, _PROMPT, _MODEL)

    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(key, _STAGE, "run-1")
        ledger.mark_running(key, "run-1")
        ledger.mark_done(key, DerivationOutput(output_hash="out", output_path="wiki/x.md"))
        row = ledger.get_derivation(key)

    assert row is not None
    assert row.status == "done"
    assert row.output_hash == "out"
    assert row.output_path == "wiki/x.md"


def test_derivation_transitions_pending_to_running_to_failed(tmp_path: Path) -> None:
    """Given a running row, when it is marked failed, then status is failed and error is kept."""
    key = deriv_key((_UNIT_A,), "conflict", _PROMPT, _MODEL)

    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(key, "conflict", "run-1")
        ledger.mark_running(key, "run-1")
        ledger.mark_failed(key, "llm timeout")
        row = ledger.get_derivation(key)

    assert row is not None
    assert row.status == "failed"
    assert row.error == "llm timeout"


def test_mark_done_from_pending_raises_invalid_transition(tmp_path: Path) -> None:
    """Given a pending derivation, when mark_done is called, then the transition is rejected."""
    key = deriv_key((_UNIT_A,), _STAGE, _PROMPT, _MODEL)

    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(key, _STAGE, "run-1")
        with pytest.raises(InvalidDerivationTransition):
            ledger.mark_done(key, DerivationOutput(output_hash="out", output_path="wiki/x.md"))


def test_reset_stale_running_returns_foreign_rows_to_pending(tmp_path: Path) -> None:
    """Given running rows from two runs, when reset uses the current id, then only foreign rows reset."""
    stale = deriv_key((_UNIT_A,), _STAGE, _PROMPT, _MODEL)
    live = deriv_key((_UNIT_B,), _STAGE, _PROMPT, _MODEL)

    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(stale, _STAGE, "run-old")
        ledger.mark_running(stale, "run-old")
        ledger.ensure_derivation(live, _STAGE, "run-new")
        ledger.mark_running(live, "run-new")

        reset_count = ledger.reset_stale_running("run-new")

        assert reset_count == 1
        stale_row = ledger.get_derivation(stale)
        live_row = ledger.get_derivation(live)
        assert stale_row is not None
        assert live_row is not None
        assert stale_row.status == "pending"
        assert live_row.status == "running"


def test_source_item_and_unit_roundtrip(tmp_path: Path) -> None:
    """Given source and unit rows, when they are upserted, then they can be read back."""
    item = SourceItem(
        source_id="me-wiki",
        source_uri="identity/profile.md",
        source_version="1:2:" + "ab" * 32,
        content_hash="cd" * 32,
        first_seen_run="run-1",
        last_seen_run="run-1",
    )
    unit = UnitRow(
        unit_id="u-1",
        content_hash="cd" * 32,
        span="0-10",
        text_hash="ef" * 32,
        normalizer_version="n1",
    )

    with Ledger(tmp_path) as ledger:
        ledger.upsert_source_item(item)
        ledger.upsert_unit(unit)

        assert ledger.list_source_items() == (item,)
        assert ledger.get_unit("u-1") == unit


def test_rebuild_from_vault_restores_source_item_and_derivation(tmp_path: Path) -> None:
    """Given raw CAS + a cited wiki page, when rebuild runs, then source_item and derivation exist."""
    payload = b"rebuild-source-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    raw_path = tmp_path / "raw" / digest[:2] / digest
    raw_path.parent.mkdir(parents=True)
    _ = raw_path.write_bytes(payload)
    page = tmp_path / "wiki" / "profile.md"
    page.parent.mkdir(parents=True)
    _ = page.write_text(
        "\n".join(
            [
                "---",
                "id: me-wiki-identity-profile",
                "title: Profile",
                "updated: 2026-08-25",
                "compiled_by: sb/0.1.0|v1|fake",
                "status: active",
                "sources:",
                "  - sid: deadbeef",
                "    origin: me-wiki:identity/profile.md",
                f"    hash: {digest}",
                "    spans:",
                '      - "0-10"',
                "---",
                "Body.[^deadbeef]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rebuild_from_vault(tmp_path)

    with Ledger(tmp_path) as ledger:
        items = ledger.list_source_items()
        wiki_items = [item for item in items if item.source_id == "me-wiki"]
        key = deriv_key(("me-wiki-identity-profile",), "compile", "v1", "fake")
        derivation = ledger.get_derivation(key)

    assert len(wiki_items) == 1
    assert wiki_items[0].source_uri == "identity/profile.md"
    assert wiki_items[0].content_hash == digest
    assert derivation is not None
    assert derivation.status == "done"
    assert derivation.stage == "compile"
    assert derivation.output_path == "wiki/profile.md"


def _write_cas(vault: Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    raw_path = vault / "raw" / digest[:2] / digest
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    _ = raw_path.write_bytes(payload)
    return digest


def _write_wiki(vault: Path, name: str, lines: list[str]) -> None:
    page = vault / "wiki" / name
    page.parent.mkdir(parents=True, exist_ok=True)
    _ = page.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _derivation_count(vault: Path) -> int:
    completed = subprocess.run(
        ["sqlite3", str(vault / ".sb" / "ledger.db"), "SELECT COUNT(*) FROM derivation;"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(completed.stdout.strip() or "0")


def test_rebuild_unreferenced_raw_blob_creates_no_source_item(tmp_path: Path) -> None:
    """Given only an unreferenced CAS blob, when rebuild runs, then no source_item is invented."""
    _ = _write_cas(tmp_path, b"orphan-raw-bytes")

    rebuild_from_vault(tmp_path)

    with Ledger(tmp_path) as ledger:
        assert ledger.list_source_items() == ()


def test_rebuild_source_item_uses_only_k1_facts_and_verified_cas_hash(tmp_path: Path) -> None:
    """Given K1 sources plus an orphan blob, when rebuild runs, then only cited CAS facts are stored."""
    cited = _write_cas(tmp_path, b"cited-bytes")
    _ = _write_cas(tmp_path, b"orphan-bytes")
    _write_wiki(
        tmp_path,
        "cited.md",
        [
            "---",
            "id: cited-page",
            "title: Cited",
            "updated: 2026-08-25",
            "compiled_by: sb/0.1.0|v1|fake",
            "status: active",
            "sources:",
            "  - sid: cited001",
            "    origin: me-wiki:notes/cited.md",
            f"    hash: {cited}",
            "---",
            "Body.[^cited001]",
        ],
    )

    rebuild_from_vault(tmp_path)

    with Ledger(tmp_path) as ledger:
        items = ledger.list_source_items()

    assert len(items) == 1
    assert items[0].source_id == "me-wiki"
    assert items[0].source_uri == "notes/cited.md"
    assert items[0].content_hash == cited
    assert items[0].source_version == ""
    assert items[0].source_id != "raw"


def test_rebuild_missing_compiled_by_creates_no_derivation(tmp_path: Path) -> None:
    """Given a cited page without compiled_by, when rebuild runs, then no derivation is invented."""
    digest = _write_cas(tmp_path, b"no-stamp-bytes")
    _write_wiki(
        tmp_path,
        "nostamp.md",
        [
            "---",
            "id: no-stamp-page",
            "title: No Stamp",
            "updated: 2026-08-25",
            "status: active",
            "sources:",
            "  - sid: deadbeef",
            "    origin: me-wiki:nostamp.md",
            f"    hash: {digest}",
            "---",
            "Body.[^deadbeef]",
        ],
    )

    rebuild_from_vault(tmp_path)

    invented = deriv_key(("no-stamp-page",), "compile", "v1", "unknown")
    with Ledger(tmp_path) as ledger:
        items = ledger.list_source_items()
        invented_row = ledger.get_derivation(invented)
    assert len(items) == 1
    assert items[0].content_hash == digest
    assert invented_row is None
    assert _derivation_count(tmp_path) == 0


def test_rebuild_invalid_compiled_by_creates_no_derivation(tmp_path: Path) -> None:
    """Given an invalid compiled_by stamp, when rebuild runs, then no done derivation is created."""
    digest = _write_cas(tmp_path, b"bad-stamp-bytes")
    _write_wiki(
        tmp_path,
        "badstamp.md",
        [
            "---",
            "id: bad-stamp-page",
            "title: Bad Stamp",
            "updated: 2026-08-25",
            "compiled_by: not-a-valid-stamp",
            "status: active",
            "sources:",
            "  - sid: deadbeef",
            "    origin: me-wiki:badstamp.md",
            f"    hash: {digest}",
            "---",
            "Body.[^deadbeef]",
        ],
    )

    rebuild_from_vault(tmp_path)

    with Ledger(tmp_path) as ledger:
        fallback = ledger.get_derivation(deriv_key(("bad-stamp-page",), "compile", "v1", "unknown"))
    assert fallback is None
    assert _derivation_count(tmp_path) == 0


def test_rebuild_valid_compiled_by_uses_exact_prompt_and_model(tmp_path: Path) -> None:
    """Given a valid compiled_by stamp, when rebuild runs, then the derivation key uses those exact parts."""
    digest = _write_cas(tmp_path, b"exact-stamp-bytes")
    _write_wiki(
        tmp_path,
        "exact.md",
        [
            "---",
            "id: exact-page",
            "title: Exact",
            "updated: 2026-08-25",
            "compiled_by: sb/9.9.9|prompt-x|model-y",
            "status: active",
            "sources:",
            "  - sid: deadbeef",
            "    origin: me-wiki:exact.md",
            f"    hash: {digest}",
            "---",
            "Body.[^deadbeef]",
        ],
    )

    rebuild_from_vault(tmp_path)

    exact = deriv_key(("exact-page",), "compile", "prompt-x", "model-y")
    fallback = deriv_key(("exact-page",), "compile", "v1", "unknown")
    with Ledger(tmp_path) as ledger:
        row = ledger.get_derivation(exact)
        invented = ledger.get_derivation(fallback)
    assert row is not None
    assert row.status == "done"
    assert row.stage == "compile"
    assert row.output_path == "wiki/exact.md"
    assert invented is None
