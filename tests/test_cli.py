"""CLI and pipeline orchestration: lock, exit codes, logs, briefing I/O.
# noqa: SIZE_OK -- legacy CLI behavior matrix remains one test ownership surface
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from multiprocessing import Event, Process
from multiprocessing.synchronize import Event as MpEvent
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from sb.cli import main
from sb.config import Config
from sb.connectors.base import SourceAdapter
from sb.contracts import BriefingInputs, PageSpec, SourceCite, Unit
from sb.llm import LLMClient, LLMUnavailable
from sb.pipeline import (
    StageReport,
    collect_briefing_inputs,
    run_all,
    run_brief,
    run_compile,
    run_ingest,
)
from sb.store import Run, SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, load_ledger_tables
from sb.vault import Vault, init_vault

TODAY = date(2026, 8, 26)
RUNS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+ run \S+ (ok|capped|failed) pages=\d+ conflicts=\d+ errors=\d+$"
)
COMMANDS = (
    "init",
    "ingest",
    "compile",
    "brief",
    "run",
    "status",
    "rollback",
    "doctor",
    "mcp",
    "search",
    "remember",
)


def _hold_exclusive_lock(lock_path: str, held: MpEvent, release: MpEvent) -> None:
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    held.set()
    _ = release.wait(timeout=10)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _ready(tmp_path: Path) -> tuple[Config, Path]:
    root = tmp_path / "vault"
    _ = init_vault(root)
    return Config(raw={"vault_root": str(root)}), root


def _put(root: Path, data: bytes) -> str:
    return ContentAddressedStore(root).put(data)


def _page(digest: str, page_id: str = "daily/2026-08-26") -> PageSpec:
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin="me-wiki:notes/new.md", hash=digest)
    return PageSpec(page_id, "Brief", f"cited.[^{sid}]", [cite], "active")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env)


def _git_count(root: Path) -> int:
    done = _git(root, "rev-list", "--count", "HEAD")
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip())


def _cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _cli_with_config(tmp_path: Path, vault: Path, argv: list[str]) -> tuple[int, str, str]:
    cfg = tmp_path / "config.toml"
    _ = cfg.write_text(f'vault_root = "{vault}"\n', encoding="utf-8")
    previous = os.environ.get("SB_CONFIG")
    os.environ["SB_CONFIG"] = str(cfg)
    try:
        return _cli(argv)
    finally:
        if previous is None:
            _ = os.environ.pop("SB_CONFIG", None)
        else:
            os.environ["SB_CONFIG"] = previous


def _empty(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
    del ledger, vault, run_id
    return StageReport((), 0, 0, 0, False)


def _report(
    *, pages: tuple[PageSpec, ...] = (), errors: int = 0, attempted: int = 0, capped: bool = False
) -> StageReport:
    return StageReport(pages, 0, errors, attempted, capped)


def _seed_briefing(root: Path) -> BriefingInputs:
    old_hash, new_hash = "ab" + ("0" * 62), _put(root, b"new-source")
    upcoming_hash = _put(root, b"2026-08-30 ship date\n")
    with Ledger(root) as ledger:
        ledger.record_run(Run("run-yest", "2026-08-25T10:00:00+00:00", "2026-08-25T10:01:00+00:00", None, "ok"))
        ledger.record_run(Run("run-today", "2026-08-26T08:00:00+00:00", "2026-08-26T08:01:00+00:00", None, "ok"))
        ledger.upsert_source_item(SourceItem("me-wiki", "notes/new.md", "v1", new_hash, "run-yest", "run-yest"))
        ledger.upsert_source_item(SourceItem("me-wiki", "notes/old.md", "v2", new_hash, "run-today", "run-today"))
        ledger.upsert_source_item(SourceItem("me-wiki", "notes/soon.md", "v1", upcoming_hash, "run-today", "run-today"))
    _ = (root / "conflicts" / "open-alpha.md").write_text("open\n", encoding="utf-8")
    front = (
        "---\nid: old-page\nupdated: 2026-07-01\ncompiled_by: sb/0.1.0|v1|fake\n"
        f"sources:\n  - origin: me-wiki:notes/old.md\n    hash: {old_hash}\n---\nbody\n"
    )
    _ = (root / "wiki" / "old-page.md").write_text(front, encoding="utf-8")
    _ = (root / "daily" / "2026-08-25.md").write_text("yesterday brief body\n", encoding="utf-8")
    _ = (root / ".sb" / "runs.log").write_text(
        "2026-08-25T10:01:00+00:00 run run-yest failed pages=0 conflicts=0 errors=1\n", encoding="utf-8"
    )
    return BriefingInputs(
        (f"origin=me-wiki:notes/new.md hash={new_hash} [^{new_hash[:8]}] text=new-source",),
        ("conflicts/open-alpha.md",),
        (f"origin=me-wiki:notes/old.md hash={new_hash} [^{new_hash[:8]}] text=old-page",),
        (f"origin=me-wiki:notes/soon.md hash={upcoming_hash} [^{upcoming_hash[:8]}] text=2026-08-30 ship date",),
        "yesterday brief body\n",
        "failed",
    )


def test_init_creates_layout_when_temp_vault(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    cfg = tmp_path / "config.toml"
    _ = cfg.write_text(f'vault_root = "{vault}"\n', encoding="utf-8")
    monkeypatch.setenv("SB_CONFIG", str(cfg))
    code, _out, _err = _cli(["init"])
    assert code == 0
    for rel in ("wiki", "daily", "conflicts", "inbox", "raw", ".sb", "wiki/_proposed"):
        assert (vault / rel).is_dir(), rel
    assert (vault / "log.md").is_file()


def test_run_exits_0_already_running_when_lock_held(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    held, release = Event(), Event()
    worker = Process(target=_hold_exclusive_lock, args=(str(root / ".sb" / "run.lock"), held, release))
    worker.start()
    assert held.wait(timeout=5)
    try:
        outcome = run_compile(config, compiler=_empty)
        code, out, _err = _cli_with_config(tmp_path, root, ["run"])
    finally:
        release.set()
        worker.join(timeout=5)
    assert outcome.exit_code == 0
    assert outcome.already_running is True
    assert code == 0
    assert "already running" in out


def test_run_exits_1_when_stage_failure_rate_exceeds_half(tmp_path: Path) -> None:
    config, _root = _ready(tmp_path)

    def failing(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(errors=3, attempted=4)

    outcome = run_compile(config, compiler=failing)
    assert outcome.exit_code == 1
    assert outcome.status == "failed"


def test_run_exits_0_when_stage_capped(tmp_path: Path) -> None:
    config, _root = _ready(tmp_path)

    def capped(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(attempted=3, capped=True)

    outcome = run_compile(config, compiler=capped)
    assert outcome.exit_code == 0
    assert outcome.status == "capped"


def test_runs_log_matches_format_when_changed_run(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")

    def changed(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(pages=(_page(digest),), attempted=1)

    outcome = run_compile(config, compiler=changed)
    lines = (root / ".sb" / "runs.log").read_text(encoding="utf-8").splitlines()
    assert RUNS_RE.match(lines[-1])
    assert outcome.run_id in lines[-1]
    assert "ok" in lines[-1]


def test_runs_log_matches_format_when_zero_change_run(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    outcome = run_ingest(config, None, stage=_empty)
    lines = (root / ".sb" / "runs.log").read_text(encoding="utf-8").splitlines()
    assert RUNS_RE.match(lines[-1])
    assert outcome.run_id in lines[-1]


def test_log_md_appends_run_id_when_run_changed(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")

    def changed(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(pages=(_page(digest),), attempted=1)

    outcome = run_compile(config, compiler=changed)
    assert outcome.run_id in (root / "log.md").read_text(encoding="utf-8")


def test_log_md_and_commit_count_unchanged_when_zero_change(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    before_log, before_commits = (root / "log.md").read_bytes(), _git_count(root)
    _ = run_ingest(config, None, stage=_empty)
    assert (root / "log.md").read_bytes() == before_log
    assert _git_count(root) == before_commits


def test_collect_briefing_inputs_matches_fixture_when_vault_seeded(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    expected = _seed_briefing(root)
    with Ledger(root) as ledger:
        got = collect_briefing_inputs(ledger, root, today=TODAY)
    assert got == expected


def test_run_brief_passes_same_inputs_instance_to_generator(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    sentinel = BriefingInputs(("y",), ("c",), ("s",), ("u",), "lb", "ok")

    def fake_collect(ledger: Ledger, vault_root: Path, *, today: date | None = None) -> BriefingInputs:
        del ledger, vault_root, today
        return sentinel

    monkeypatch.setattr("sb.pipeline.collect_briefing_inputs", fake_collect)
    seen: list[BriefingInputs] = []

    def stub(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del llm, config
        seen.append(inputs)
        return _page(digest)

    _ = run_brief(config, generator=stub)
    assert seen == [sentinel]
    assert seen[0] is sentinel


def test_help_lists_eleven_subcommands() -> None:
    code, out, _err = _cli(["--help"])
    assert code == 0
    for name in COMMANDS:
        assert name in out


def test_invalid_command_exits_nonzero() -> None:
    code, _out, _err = _cli(["nosuch"])
    assert code != 0


def test_status_exits_0_when_temp_vault_initialized(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    code, _out, _err = _cli_with_config(tmp_path, root, ["status"])
    assert code == 0


def test_resets_stale_running_when_new_run_starts(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation("stale-key", "compile", "old-run")
        ledger.mark_running("stale-key", "old-run")
    seen: list[str] = []

    def check(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del vault, run_id
        row = ledger.get_derivation("stale-key")
        assert row is not None
        seen.append(row.status)
        return _report(attempted=1)

    _ = run_compile(config, compiler=check)
    assert seen == ["pending"]


def test_changed_run_commit_contains_log_md_and_tree_is_clean(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")

    def changed(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(pages=(_page(digest),), attempted=1)

    outcome = run_compile(config, compiler=changed)
    shown = _git(root, "show", "HEAD:log.md")
    assert shown.returncode == 0
    assert outcome.run_id in shown.stdout
    assert _git(root, "status", "--porcelain").stdout == ""


def test_status_includes_run_id_counts_and_status_after_run(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")

    def changed(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(pages=(_page(digest),), attempted=1)

    outcome = run_compile(config, compiler=changed)
    code, out, _err = _cli_with_config(tmp_path, root, ["status"])
    assert code == 0
    assert outcome.run_id in out
    assert "pages=" in out
    assert "conflicts=" in out
    assert "errors=" in out
    assert any(token in out for token in ("ok", "capped", "failed"))


def test_ingest_then_compile_writes_page_when_markdown_source_present(tmp_path: Path) -> None:
    from sb.contracts import Blob
    from sb.normalize import normalize
    from sb.parsers import parser_for

    src = tmp_path / "src"
    _ = src.mkdir()
    body = b"Alpha fact for compile.\n"
    _ = (src / "note.md").write_bytes(body)
    vault = tmp_path / "vault"
    _ = init_vault(vault)
    config = Config(
        raw={
            "vault_root": str(vault),
            "sources": [{"id": "me-wiki", "adapter": "markdown-vault", "root": str(src)}],
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }
    )
    ingested = run_ingest(config, ("me-wiki", "markdown-vault"))
    assert ingested.exit_code == 0
    with Ledger(vault) as ledger:
        items = ledger.list_source_items()
        assert items
        cas = ContentAddressedStore(vault)
        item = next(row for row in items if cas.exists(row.content_hash))
        assert cas.exists(item.content_hash)
        assert ledger.get_cursor(item.source_id)
        text = parser_for(".md")(cas.get(item.content_hash))
        units = normalize(Blob(item.content_hash, len(body)), text, f"{item.source_id}:{item.source_uri}")
        assert units
        assert ledger.get_unit(units[0].unit_id) is not None
    compiled = run_compile(config, llm_mode="fake")
    assert compiled.exit_code == 0
    wiki_pages = [path for path in (vault / "wiki").rglob("*.md") if "_proposed" not in path.parts]
    assert wiki_pages
    assert compiled.run_id in _git(vault, "show", "HEAD:log.md").stdout
    assert _git(vault, "status", "--porcelain").stdout == ""


def test_rollback_missing_id_returns_controlled_cli_error(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    code, out, err = _cli_with_config(tmp_path, root, ["rollback", "missing-run"])
    assert code != 0
    text = f"{out}{err}"
    assert "traceback" not in text.lower()
    assert text.strip() == "ROLLBACK_REQUIRES_GENERATION_AUTHORITY"


def _deriv_count(root: Path) -> int:
    return len(load_ledger_tables(root / ".sb" / "ledger.db").derivations)


def _seed_status(root: Path, status: str = "ok") -> None:
    runs = root / ".sb" / "runs.log"
    if root.is_symlink():
        runs.parent.chmod(0o700)
        runs.chmod(0o600)
    _ = runs.write_text(
        f"2026-08-25T00:00:00+00:00 run seed {status} pages=0 conflicts=0 errors=0\n",
        encoding="utf-8",
    )


def test_identical_brief_pages_leave_commit_and_log_unchanged(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    page = _page(digest, page_id="daily/fixture")

    def gen(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del inputs, llm, config
        return page

    first = run_brief(config, generator=gen)
    assert first.git_commit is not None
    before_log = (root / "log.md").read_bytes()
    before_commits = _git_count(root)
    second = run_brief(config, generator=gen)
    assert second.git_commit is None
    assert _git_count(root) == before_commits
    assert (root / "log.md").read_bytes() == before_log
    assert _git(root, "status", "--porcelain").stdout == ""
    assert (root / "log.md").read_text(encoding="utf-8").count(first.run_id) == 1


def test_equivalent_brief_skips_llm_and_derivation_when_facts_match(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    _seed_status(root)
    fake = FakeLLM(["없음", "없음"])

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    monkeypatch.setattr("sb.pipeline._llm", provide)
    first = run_brief(config, llm_mode="fake")
    assert first.exit_code == 0
    assert fake.calls == 1
    before_deriv = _deriv_count(root)
    before_log = (root / "log.md").read_bytes()
    before_head = _git(root, "rev-parse", "HEAD").stdout
    before_runs = (root / ".sb" / "runs.log").read_text(encoding="utf-8").count("\n")
    second = run_brief(config, llm_mode="fake")
    assert second.exit_code == 0
    assert fake.calls == 1
    assert _deriv_count(root) == before_deriv
    assert (root / "log.md").read_bytes() == before_log
    assert _git(root, "rev-parse", "HEAD").stdout == before_head
    assert (root / ".sb" / "runs.log").read_text(encoding="utf-8").count("\n") == before_runs + 1


def test_changed_briefing_facts_open_new_derivation_and_commit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    _seed_status(root)
    fake = FakeLLM(["없음", "없음"])

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    monkeypatch.setattr("sb.pipeline._llm", provide)
    first = run_brief(config, llm_mode="fake")
    assert fake.calls == 1
    before_deriv = _deriv_count(root)
    before_head = _git(root, "rev-parse", "HEAD").stdout
    (root / "conflicts").chmod(0o700)
    _ = (root / "conflicts" / "open-x.md").write_text("conflict\n", encoding="utf-8")
    second = run_brief(config, llm_mode="fake")
    assert fake.calls == 2
    assert _deriv_count(root) == before_deriv + 1
    assert _git_count(root) == 1
    assert _git(root, "rev-parse", "HEAD").stdout != before_head
    assert second.git_commit is not None
    assert first.run_id != second.run_id


def test_brief_generator_failure_marks_derivation_failed_without_commit(
    tmp_path: Path,
) -> None:
    config, root = _ready(tmp_path)
    _seed_status(root)
    before_log = (root / "log.md").read_bytes()
    before_commits = _git_count(root)

    def boom(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del inputs, llm, config
        raise LLMUnavailable(attempts=1, reason="down")

    outcome = run_brief(config, generator=boom)
    assert outcome.exit_code == 1
    assert outcome.status == "failed"
    assert outcome.git_commit is None
    rows = load_ledger_tables(root / ".sb" / "ledger.db").derivations.values()
    assert any(row.stage == "brief" and row.status == "failed" for row in rows)
    assert (root / "log.md").read_bytes() == before_log
    assert _git_count(root) == before_commits
    assert _git(root, "status", "--porcelain").stdout == ""


def test_lint_failure_with_run_log_line_leaves_log_and_index_clean(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    before_log = (root / "log.md").read_bytes()
    before_porc = _git(root, "status", "--porcelain").stdout
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/new.md", hash=digest)
    bad = PageSpec("daily/bad", "Bad", "broken.[^zzzzzzzz]", [cite], "active")

    def failing(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return _report(pages=(bad,), attempted=1)

    outcome = run_compile(config, compiler=failing)
    assert outcome.exit_code == 1
    assert outcome.status == "failed"
    assert (root / "log.md").read_bytes() == before_log
    assert _git(root, "status", "--porcelain").stdout == before_porc


CITE_ITEM_RE = re.compile(
    r"origin=\S+ hash=[0-9a-fA-F]{64} \[\^[0-9a-fA-F]{8}\] text="
)


def test_collect_briefing_inputs_emits_parseable_citation_items(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    _ = _seed_briefing(root)
    with Ledger(root) as ledger:
        got = collect_briefing_inputs(ledger, root, today=TODAY)
    assert got.yesterday_items
    for item in got.yesterday_items:
        assert CITE_ITEM_RE.search(item)
        assert "origin=" in item and "hash=" in item and "text=" in item


def test_fake_llm_brief_writes_linted_daily_page_when_inputs_are_cited(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    _ = _seed_briefing(root)
    _seed_status(root)
    outcome = run_brief(config, llm_mode="fake")
    assert outcome.exit_code == 0
    dailies = list((root / "daily").glob("*.md"))
    assert any(
        "[^" in path.read_text(encoding="utf-8") and "sid:" in path.read_text(encoding="utf-8")
        for path in dailies
    )


def test_brief_lint_failure_does_not_mark_done_and_rerun_calls_generator(
    tmp_path: Path,
) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    _seed_status(root)
    calls = {"n": 0}
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/new.md", hash=digest)
    bad = PageSpec("daily/x", "X", "bad.[^zzzzzzzz]", [cite], "active")

    def gen(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del inputs, llm, config
        calls["n"] += 1
        return bad

    first = run_brief(config, generator=gen)
    assert first.exit_code == 1
    rows = load_ledger_tables(root / ".sb" / "ledger.db").derivations.values()
    assert not any(row.stage == "brief" and row.status == "done" for row in rows)
    second = run_brief(config, generator=gen)
    assert calls["n"] == 2
    assert second.exit_code == 1


def test_brief_vault_failure_marks_original_key_failed_and_retries_same_key(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    _seed_status(root)
    before_log = (root / "log.md").read_bytes()
    before_commits = _git_count(root)
    calls = {"n": 0}
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/new.md", hash=digest)
    bad = PageSpec("daily/x", "X", "bad.[^zzzzzzzz]", [cite], "active")
    good = _page(digest, page_id="daily/ok")

    def gen(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del inputs, llm, config
        calls["n"] += 1
        return bad if calls["n"] == 1 else good

    first = run_brief(config, generator=gen)
    assert first.exit_code == 1
    assert first.status == "failed"
    assert first.git_commit is None
    briefs = [row for row in load_ledger_tables(root / ".sb" / "ledger.db").derivations.values() if row.stage == "brief"]
    assert len(briefs) == 1
    key = briefs[0].deriv_key
    assert briefs[0].status == "failed"
    assert briefs[0].status != "running"
    assert (root / "log.md").read_bytes() == before_log
    assert _git_count(root) == before_commits
    assert "failed" in (root / ".sb" / "runs.log").read_text(encoding="utf-8")

    def boom_brief(inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec:
        del inputs, llm, config
        return bad

    monkeypatch.setattr("sb.briefing.generate_briefing", boom_brief)
    code, out, err = _cli_with_config(tmp_path, root, ["brief", "--llm", "fake"])
    assert code != 0
    assert "traceback" not in f"{out}{err}".lower()
    _seed_status(root, "ok")
    second = run_brief(config, generator=gen)
    assert calls["n"] == 2
    after = load_ledger_tables(root / ".sb" / "ledger.db").derivations[key]
    assert after.deriv_key == key
    assert after.status == "done"
    assert second.exit_code == 0
    assert second.git_commit is not None


def test_run_all_records_failed_run_without_traceback(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config, root = _ready(tmp_path)
    digest = _put(root, b"blob")
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/new.md", hash=digest)
    bad = PageSpec("wiki/bad", "Bad", "nope.[^zzzzzzzz]", [cite], "active")

    def boom(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return [bad]

    def no_adapters(config: Config) -> dict[str, SourceAdapter]:
        del config
        return {}

    monkeypatch.setattr("sb.compile.compile_pages", boom)
    monkeypatch.setattr("sb.connectors.discover_adapters", no_adapters)
    outcome = run_all(config)
    assert outcome.exit_code == 1
    assert outcome.status == "failed"
    log = (root / ".sb" / "runs.log").read_text(encoding="utf-8")
    assert "failed" in log
    code, out, err = _cli_with_config(tmp_path, root, ["run"])
    assert code != 0
    assert "traceback" not in f"{out}{err}".lower()


def test_ingest_cap_bounds_attempts_before_cas_put(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from sb.contracts import SourceRef

    config, root = _ready(tmp_path)
    config = Config(raw={"vault_root": str(root), "caps": {"max_new_units_per_run": 3}})

    class Flood:
        source_id: str = "flood"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            for index in range(10):
                yield SourceRef("flood", f"n{index}.zzz", "v"), b"not-a-parser-format", {}

        def next_cursor(self) -> str:
            return "end"

    def flood_adapters(config: Config) -> dict[str, Flood]:
        del config
        return {"flood": Flood()}

    monkeypatch.setattr("sb.connectors.discover_adapters", flood_adapters)
    outcome = run_ingest(config, None)
    blobs = [path for path in (root / "raw").rglob("*") if path.is_file() and not path.name.startswith(".")]
    assert len(blobs) <= 3
    assert outcome.errors == 0
    assert outcome.status == "capped"
    assert outcome.exit_code == 0


def test_compile_routes_conflict_pages_through_vault(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.conflict import ConflictFinding
    from sb.contracts import ConflictVerdict

    config, root = _ready(tmp_path)
    digest = _put(root, b"cited-body")
    sid = digest[:8]
    compiled = PageSpec("wiki/src", "Src", f"fact.[^{sid}]", [SourceCite(sid, "me-wiki:a.md", digest)], "active")
    conflict = PageSpec(
        "conflicts/open-x", "Conflict", f"clash.[^{sid}]", [SourceCite(sid, "me-wiki:a.md", digest)], "conflicted"
    )

    def fake_compile(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return [compiled]

    def fake_check(
        units: list[Unit], pages: list[PageSpec], ledger: Ledger, llm: LLMClient, config: Config
    ) -> list[ConflictFinding]:
        del units, pages, ledger, llm, config
        verdict = ConflictVerdict("contradicts", 0.9, "clash")
        return [ConflictFinding("a", "b", verdict, "conflict", conflict, None, (sid,), False)]

    monkeypatch.setattr("sb.compile.compile_pages", fake_compile)
    monkeypatch.setattr("sb.conflict.check", fake_check)
    outcome = run_compile(config, llm_mode="fake")
    assert outcome.exit_code == 0
    assert (root / "conflicts" / "open-x.md").is_file()


def test_doctor_exits_nonzero_when_citation_unresolved(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    _ = (root / "wiki" / "broken.md").write_text(
        "---\nid: broken\nsources: []\n---\nHi.[^deadbeef]\n", encoding="utf-8"
    )
    code, _out, err = _cli_with_config(tmp_path, root, ["doctor"])
    assert code != 0
    assert "traceback" not in err.lower()


def test_second_sb_run_exit0_no_new_commit_when_source_items_unchanged(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.contracts import SourceRef
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    config = Config(raw={"vault_root": str(root), "caps": {"max_new_units_per_run": 10}, "llm": {"prompt_version": "v1", "model_id": "fake"}})
    fake = FakeLLM(["없음", "없음"])

    class Mixed:
        source_id: str = "mix"
        versions: dict[str, str]

        def __init__(self) -> None:
            self.versions = {"good.md": "v1", "bad.zzz": "v1", "skip.dat": "v1"}

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            yield SourceRef("mix", "good.md", self.versions["good.md"]), b"ok note\n", {}
            yield SourceRef("mix", "bad.zzz", self.versions["bad.zzz"]), b"nope", {}
            yield SourceRef("mix", "skip.dat", self.versions["skip.dat"]), b"", {"skip_reason": "denied-path"}

        def next_cursor(self) -> str:
            return "end"

    mixed = Mixed()

    def adapters(config: Config) -> dict[str, Mixed]:
        del config
        return {"mix": mixed}

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    def empty_compile(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return []

    def empty_check(
        units: list[Unit], pages: list[PageSpec], ledger: Ledger, llm: LLMClient, config: Config
    ) -> list[PageSpec]:
        del units, pages, ledger, llm, config
        return []

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)
    monkeypatch.setattr("sb.pipeline._llm", provide)
    monkeypatch.setattr("sb.compile.compile_pages", empty_compile)
    monkeypatch.setattr("sb.conflict.check", empty_check)
    probe = run_ingest(config, None)
    assert probe.exit_code == 0
    assert probe.status in {"ok", "capped"}
    first = run_all(config)
    assert first.exit_code == 0
    commits = _git_count(root)
    derivs = _deriv_count(root)
    calls = fake.calls
    second = run_all(config)
    assert second.exit_code == 0
    assert second.pages == 0
    assert second.errors == 0
    assert _git_count(root) == commits
    assert _deriv_count(root) == derivs
    assert fake.calls == calls
    mixed.versions["bad.zzz"] = "v2"
    third = run_ingest(config, None)
    assert third.exit_code == 0
    assert third.status in {"ok", "capped"}
    tight = Config(raw={"vault_root": str(root), "caps": {"max_new_units_per_run": 2}})

    class Flood:
        source_id: str = "flood"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            for index in range(5):
                yield SourceRef("flood", f"n{index}.zzz", "v1"), b"nope", {}

        def next_cursor(self) -> str:
            return "end"

    def flood_only(config: Config) -> dict[str, Flood]:
        del config
        return {"flood": Flood()}

    monkeypatch.setattr("sb.connectors.discover_adapters", flood_only)
    wave1 = run_ingest(tight, None)
    assert wave1.status == "capped"
    assert wave1.exit_code == 0
    wave2 = run_ingest(tight, None)
    assert wave2.status == "capped"
    assert wave2.exit_code == 0
    assert wave2.errors == 0


def test_brief_facts_stable_when_only_previous_run_status_changes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    _seed_status(root, "ok")
    fake = FakeLLM(["없음", "없음"])

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    monkeypatch.setattr("sb.pipeline._llm", provide)
    first = run_brief(config, llm_mode="fake")
    assert first.exit_code == 0
    assert fake.calls == 1
    before_deriv = _deriv_count(root)
    before_commits = _git_count(root)
    _seed_status(root, "failed")
    second = run_brief(config, llm_mode="fake")
    assert second.exit_code == 0
    assert fake.calls == 1
    assert _deriv_count(root) == before_deriv
    assert _git_count(root) == before_commits
    assert second.git_commit is None


def test_ingest_started_at_uses_host_local_date(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    today = datetime.now().astimezone().date()
    yesterday = today - timedelta(days=1)
    utc_evening = datetime(yesterday.year, yesterday.month, yesterday.day, 21, 59, 29, tzinfo=UTC)
    local_day = utc_evening.astimezone().date()
    digest = _put(root, b"omo-session\n")
    offset_stamp = utc_evening.isoformat()
    z_stamp = utc_evening.strftime("%Y-%m-%dT%H:%M:%SZ")
    with Ledger(root) as ledger:
        ledger.record_run(Run("run-offset", offset_stamp, offset_stamp, None, "ok"))
        ledger.record_run(Run("run-z", z_stamp, z_stamp, None, "ok"))
        ledger.upsert_source_item(SourceItem("omo", "sess/offset", "v1", digest, "run-offset", "run-offset"))
        ledger.upsert_source_item(SourceItem("omo", "sess/z", "v1", digest, "run-z", "run-z"))
    with Ledger(root) as ledger:
        got = collect_briefing_inputs(ledger, root, today=today)
    if local_day == today:
        assert all("sess/offset" not in item and "sess/z" not in item for item in got.yesterday_items)
    if local_day == yesterday:
        assert any("sess/offset" in item for item in got.yesterday_items)
    fake = FakeLLM(["없음", "없음"])

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    monkeypatch.setattr("sb.pipeline._llm", provide)
    first = run_brief(config, llm_mode="fake")
    assert first.exit_code == 0
    daily = root / "daily" / f"{today.isoformat()}.md"
    before_hash = daily.read_bytes() if daily.is_file() else b""
    before_deriv = _deriv_count(root)
    before_calls = fake.calls
    second = run_brief(config, llm_mode="fake")
    assert second.exit_code == 0
    assert fake.calls == before_calls
    assert _deriv_count(root) == before_deriv
    if daily.is_file():
        assert daily.read_bytes() == before_hash


def test_quarantine_only_ingest_is_ok_or_capped(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from sb.contracts import SourceRef
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    config = Config(raw={"vault_root": str(root), "caps": {"max_new_units_per_run": 10}, "llm": {"prompt_version": "v1", "model_id": "fake"}})
    fake = FakeLLM(["없음", "없음"])

    class QuarantineOnly:
        source_id: str = "q"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            yield SourceRef("q", "a.zzz", "v1"), b"nope", {}
            yield SourceRef("q", "b.dat", "v1"), b"", {"skip_reason": "denied-path"}
            yield SourceRef("q", "c.zzz", "v1"), b"still-nope", {}

        def next_cursor(self) -> str:
            return "end"

    def adapters(config: Config) -> dict[str, QuarantineOnly]:
        del config
        return {"q": QuarantineOnly()}

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    def empty_compile(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return []

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)
    monkeypatch.setattr("sb.pipeline._llm", provide)
    monkeypatch.setattr("sb.compile.compile_pages", empty_compile)
    first = run_all(config)
    assert first.exit_code == 0
    assert first.status in {"ok", "capped"}
    commits = _git_count(root)
    derivs = _deriv_count(root)
    calls = fake.calls
    second = run_all(config)
    assert second.exit_code == 0
    assert second.errors == 0
    assert _git_count(root) == commits
    assert _deriv_count(root) == derivs
    assert fake.calls == calls


def test_brief_skipped_when_compile_pages_zero_and_no_new_units(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.contracts import SourceRef
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    fake = FakeLLM(["없음", "없음"])

    class Seen:
        source_id: str = "mix"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            yield SourceRef("mix", "good.md", "v1"), b"ok note\n", {}
            yield SourceRef("mix", "skip.dat", "v1"), b"", {"skip_reason": "denied-path"}

        def next_cursor(self) -> str:
            return "end"

    def adapters(config: Config) -> dict[str, Seen]:
        del config
        return {"mix": Seen()}

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    def empty_compile(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return []

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)
    monkeypatch.setattr("sb.pipeline._llm", provide)
    monkeypatch.setattr("sb.compile.compile_pages", empty_compile)
    _ = run_ingest(config, None)
    daily_dir = root / "daily"
    before_files = {path.name: path.read_bytes() for path in daily_dir.glob("*.md")}
    before_deriv = _deriv_count(root)
    before_calls = fake.calls
    outcome = run_all(config)
    assert outcome.exit_code == 0
    assert outcome.status in {"ok", "capped"}
    assert fake.calls == before_calls
    assert _deriv_count(root) == before_deriv
    after_files = {path.name: path.read_bytes() for path in daily_dir.glob("*.md")}
    assert after_files == before_files
    briefs = [row for row in load_ledger_tables(root / ".sb" / "ledger.db").derivations.values() if row.stage == "brief"]
    assert not any(row.status == "failed" for row in briefs)


def test_rebucketed_existing_source_dates_do_not_change_brief_key(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from sb.contracts import SourceRef
    from sb.llm import FakeLLM

    config, root = _ready(tmp_path)
    today = datetime.now().astimezone().date()
    yesterday = today - timedelta(days=1)
    utc_stamp = datetime(yesterday.year, yesterday.month, yesterday.day, 20, 35, 55, tzinfo=UTC).isoformat()
    fake = FakeLLM(["없음", "없음"])
    digest = _put(root, b"profile body\n")
    with Ledger(root) as ledger:
        ledger.record_run(Run("run-old", utc_stamp, utc_stamp, None, "ok"))
        for index in range(17):
            ledger.upsert_source_item(
                SourceItem("me-wiki", f"identity/p{index}.md", "v1", digest, "run-old", "run-old")
            )

    class Extra:
        source_id: str = "me-wiki"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            del cursor
            for index in range(17):
                yield SourceRef("me-wiki", f"identity/p{index}.zzz", "v2"), b"nope", {}

        def next_cursor(self) -> str:
            return "end"

    def adapters(config: Config) -> dict[str, Extra]:
        del config
        return {"me-wiki": Extra()}

    def provide(config: Config, llm_mode: str) -> FakeLLM:
        del config, llm_mode
        return fake

    def empty_compile(units: list[Unit], ledger: Ledger, llm: LLMClient, config: Config) -> list[PageSpec]:
        del units, ledger, llm, config
        return []

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)
    monkeypatch.setattr("sb.pipeline._llm", provide)
    monkeypatch.setattr("sb.compile.compile_pages", empty_compile)
    first = run_brief(config, llm_mode="fake")
    assert first.exit_code == 0
    real_collect = collect_briefing_inputs

    def shifted(
        ledger: Ledger, vault_root: Path, *, today: date | None = None
    ) -> BriefingInputs:
        base = real_collect(ledger, vault_root, today=today)
        return BriefingInputs(
            ("origin=me-wiki:rebucket.md hash=" + digest + f" [^{digest[:8]}] text=rebucket",)
            + base.yesterday_items,
            base.open_conflict_pages,
            base.stale_pages,
            base.upcoming_items,
            base.last_brief,
            base.previous_run_status,
        )

    monkeypatch.setattr("sb.pipeline.collect_briefing_inputs", shifted)
    before_calls = fake.calls
    before_failed = [
        row
        for row in load_ledger_tables(root / ".sb" / "ledger.db").derivations.values()
        if row.stage == "brief" and row.status == "failed"
    ]
    before_deriv = _deriv_count(root)
    daily = root / "daily" / f"{today.isoformat()}.md"
    before_daily = daily.read_bytes() if daily.is_file() else b""
    outcome = run_all(config)
    assert outcome.exit_code == 0
    assert fake.calls == before_calls
    assert _deriv_count(root) == before_deriv
    failed = [
        row
        for row in load_ledger_tables(root / ".sb" / "ledger.db").derivations.values()
        if row.stage == "brief" and row.status == "failed"
    ]
    assert failed == before_failed
    if daily.is_file():
        assert daily.read_bytes() == before_daily


class _NoCompiledHash:
    """Test ledger: every page is new, so the compiled-hash lookup stays empty."""

    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed_page(root: Path, page_id: str, title: str, body: str) -> None:
    digest = _put(root, b"cli-search-seed")
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin="me-wiki:notes/x.md", hash=digest)
    spec = PageSpec(page_id, title, f"# {title}\n{body}[^{sid}]\n", [cite], "active")
    _ = Vault(root=root).write_pages((spec,), "run-cli-search", _NoCompiledHash())


def test_remember_writes_inbox_note(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    argv = ["remember", "계약서 수요일 발송", "--title", "계약"]
    code, out, _err = _cli_with_config(tmp_path, root, argv)
    assert code == 0
    rel = out.strip()
    assert rel.startswith("inbox/")
    assert rel.endswith("-계약.md")
    assert (root / rel).read_text(encoding="utf-8") == "계약서 수요일 발송"


def test_remember_rejects_blank_content_without_writing(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    code, _out, err = _cli_with_config(tmp_path, root, ["remember", "   "])
    assert code == 2
    assert "requires content" in err
    assert list((root / "inbox").glob("*.md")) == []


def test_search_reports_no_match_on_fresh_vault(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    code, out, _err = _cli_with_config(tmp_path, root, ["search", "AlphaEngineer"])
    assert code == 0
    assert out.strip() == "no match"


def test_search_json_emits_empty_array_on_fresh_vault(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    code, out, _err = _cli_with_config(tmp_path, root, ["search", "AlphaEngineer", "--json"])
    assert code == 0
    assert json.loads(out) == []


def test_search_prints_page_id_and_snippet_for_a_hit(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    _seed_page(root, "wiki/alpha", "Alpha", "AlphaEngineer builds tools.")
    code, out, _err = _cli_with_config(tmp_path, root, ["search", "AlphaEngineer"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "wiki/alpha — Alpha"
    assert lines[1].startswith("  ")
    assert lines[1].strip() != ""


def test_search_json_carries_page_id_for_a_hit(tmp_path: Path) -> None:
    _config, root = _ready(tmp_path)
    _seed_page(root, "wiki/alpha", "Alpha", "AlphaEngineer builds tools.")
    code, out, _err = _cli_with_config(tmp_path, root, ["search", "AlphaEngineer", "--json"])
    assert code == 0
    hits = cast(list[dict[str, object]], json.loads(out))
    assert [hit["page_id"] for hit in hits] == ["wiki/alpha"]
