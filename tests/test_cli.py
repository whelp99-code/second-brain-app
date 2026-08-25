"""CLI and pipeline orchestration: lock, exit codes, logs, briefing I/O."""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from multiprocessing import Event, Process
from multiprocessing.synchronize import Event as MpEvent
from pathlib import Path

from pytest import MonkeyPatch

from sb.cli import main
from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.llm import LLMClient
from sb.pipeline import StageReport, collect_briefing_inputs, run_brief, run_compile, run_ingest
from sb.store import Run, SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

TODAY = date(2026, 8, 26)
RUNS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+ run \S+ (ok|capped|failed) pages=\d+ conflicts=\d+ errors=\d+$"
)
COMMANDS = ("init", "ingest", "compile", "brief", "run", "status", "rollback", "doctor", "mcp")


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


def _git_count(root: Path) -> int:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    done = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=root, capture_output=True, text=True, check=False, env=env
    )
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
        ("me-wiki:notes/new.md",), ("conflicts/open-alpha.md",), ("old-page",),
        ("2026-08-30 ship date",), "yesterday brief body\n", "failed",
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


def test_help_lists_nine_subcommands() -> None:
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
