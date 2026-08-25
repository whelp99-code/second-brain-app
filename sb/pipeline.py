"""Thin run orchestration: lock, ledger, logs, briefing I/O, vault writes."""

from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from uuid import uuid4

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec
from sb.llm import LLMClient
from sb.store import Run, SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, parse_page_frontmatter
from sb.vault import Vault

STALE_AFTER: Final = timedelta(days=30)
UPCOMING_WINDOW: Final = timedelta(days=7)
_UPDATED: Final = re.compile(r"^updated:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True, slots=True)
class StageReport:
    pages: tuple[PageSpec, ...]
    conflicts: int
    errors: int
    attempted: int
    capped: bool


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    status: str
    pages: int
    conflicts: int
    errors: int
    exit_code: int
    git_commit: str | None
    already_running: bool = False


class StageFn(Protocol):
    def __call__(self, ledger: Ledger, vault: Vault, run_id: str) -> StageReport: ...


class BriefGenerator(Protocol):
    def __call__(self, inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec: ...


class _NoHashes:
    def last_compiled_hash(self, page_id: str) -> str | None:
        _ = page_id
        return None


@contextmanager
def _run_lock(root: Path) -> Generator[bool]:
    path = root / ".sb" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _as_date(stamp: str) -> date | None:
    try:
        return datetime.fromisoformat(stamp).date()
    except ValueError:
        return None


def _source_changed(ledger: Ledger, sources: tuple[tuple[str, str], ...]) -> bool:
    items = ledger.list_source_items()
    for origin, digest in sources:
        source_id, _sep, uri = origin.partition(":")
        hashes = [row.content_hash for row in items if row.source_id == source_id and row.source_uri == uri]
        if any(item_hash != digest for item_hash in hashes):
            return True
    return False


def collect_briefing_inputs(
    ledger: Ledger, vault_root: Path, *, today: date | None = None
) -> BriefingInputs:
    """Load K4 briefing inputs from the ledger and tracked vault files."""
    day = datetime.now(UTC).date() if today is None else today
    root = Path(vault_root)
    yesterday = day - timedelta(days=1)
    y_items = [
        f"{item.source_id}:{item.source_uri}"
        for item in ledger.list_source_items()
        if (run := ledger.get_run(item.first_seen_run)) is not None and _as_date(run.started_at) == yesterday
    ]
    conflicts = root / "conflicts"
    open_pages = (
        () if not conflicts.is_dir()
        else tuple(sorted(path.relative_to(root).as_posix() for path in conflicts.glob("*.md")))
    )
    wiki, cas, start, end = root / "wiki", ContentAddressedStore(root), day - UPCOMING_WINDOW, day + UPCOMING_WINDOW
    stale: list[str] = []
    if wiki.is_dir():
        cutoff = day - STALE_AFTER
        for path in wiki.rglob("*.md"):
            if "_proposed" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            matched = _UPDATED.search(text)
            facts = parse_page_frontmatter(text)
            if matched is None or date.fromisoformat(matched.group(1)) > cutoff or facts is None:
                continue
            if _source_changed(ledger, facts.sources):
                stale.append(facts.page_id)
    upcoming: list[str] = []
    for item in ledger.list_source_items():
        run = ledger.get_run(item.last_seen_run)
        seen = None if run is None else _as_date(run.started_at)
        if seen is None or seen < start or not cas.exists(item.content_hash):
            continue
        for raw in cas.get(item.content_hash).decode("utf-8", errors="replace").splitlines():
            matched = _ISO_DATE.search(raw)
            if matched is None:
                continue
            when = date.fromisoformat(matched.group(0))
            if day <= when <= end:
                upcoming.append(raw.strip())
    dailies: list[tuple[date, Path]] = []
    if (root / "daily").is_dir():
        for candidate in (root / "daily").glob("*.md"):
            try:
                stamp = date.fromisoformat(candidate.stem)
            except ValueError:
                continue
            if stamp < day:
                dailies.append((stamp, candidate))
    last = max(dailies)[1].read_text(encoding="utf-8") if dailies else None
    return BriefingInputs(tuple(sorted(y_items)), open_pages, tuple(sorted(stale)), tuple(upcoming), last, read_status_line(root))


def read_status_line(root: Path) -> str | None:
    path = root / ".sb" / "runs.log"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    parts = lines[-1].split() if lines else []
    return None if len(parts) < 4 else parts[3]


def _run_locked(root: Path, stage: StageFn) -> RunOutcome:
    run_id, started, vault = uuid4().hex, datetime.now(UTC).isoformat(), Vault(root=root)
    with Ledger(root) as ledger:
        _ = ledger.reset_stale_running(run_id)
        report = stage(ledger, vault, run_id)
        status, exit_code = ("capped", 0) if report.capped else (
            ("failed", 1) if report.attempted > 0 and report.errors * 2 > report.attempted else ("ok", 0)
        )
        commit, pages, conflicts = None, 0, report.conflicts
        rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={report.errors}"
        if report.pages:
            vault.append_log(rendered.format(len(report.pages), conflicts))
            result = vault.write_pages(report.pages, run_id, _NoHashes())
            commit, pages, conflicts = result.commit, result.pages, result.conflicts
        ledger.record_run(Run(run_id, started, datetime.now(UTC).isoformat(), commit, status))
        log = root / ".sb" / "runs.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            _ = handle.write(rendered.format(pages, conflicts) + "\n")
        return RunOutcome(run_id, status, pages, conflicts, report.errors, exit_code, commit)


def _execute(config: Config, stage: StageFn) -> RunOutcome:
    root = Path(config.vault_root)
    with _run_lock(root) as acquired:
        if not acquired:
            return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
        return _run_locked(root, stage)


def _ingest(config: Config, source_ids: Sequence[str] | None, limit: int | None) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        from sb.connectors import discover_adapters

        chosen = discover_adapters(config)
        adapters = [chosen[sid] for sid in source_ids if sid in chosen] if source_ids is not None else list(chosen.values())
        cas, cap = ContentAddressedStore(vault.root), config.caps["max_new_units_per_run"] if limit is None else limit
        errors = attempted = written = 0
        capped = False
        for adapter in adapters:
            try:
                items = adapter.scan(ledger.get_cursor(adapter.source_id))
            except (OSError, RuntimeError):
                errors += 1
                attempted += 1
                continue
            for ref, data, meta in items:
                if written >= cap:
                    capped = True
                    break
                attempted += 1
                if meta.get("skip_reason"):
                    continue
                try:
                    digest = cas.put(data)
                    ledger.upsert_source_item(
                        SourceItem(ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id)
                    )
                    written += 1
                except OSError:
                    errors += 1
            if capped:
                break
            ledger.set_cursor(adapter.source_id, adapter.next_cursor(), datetime.now(UTC).isoformat())
        return StageReport((), 0, errors, attempted, capped)

    return stage


def _llm(config: Config, llm_mode: str) -> LLMClient:
    from sb.llm import CliLLM, FakeLLM

    return FakeLLM([]) if llm_mode == "fake" else CliLLM(list(config.llm.argv_template))


def _compile_stage(config: Config, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        try:
            from sb.compile import compile_pages
        except ModuleNotFoundError:
            return StageReport((), 0, 0, 0, False)
        pages = list(compile_pages([], ledger, _llm(config, llm_mode), config))
        capped = bool(pages) and pages[-1].status == "CAPPED"
        kept = pages[:-1] if capped else pages
        return StageReport(tuple(kept), 0, 0, len(pages), capped) if vault and run_id else StageReport((), 0, 0, 0, False)

    return stage


def _brief_stage(config: Config, generator: BriefGenerator | None, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        inputs = collect_briefing_inputs(ledger, vault.root)
        if generator is not None:
            return StageReport((generator(inputs, None, config),), 0, 0, 1, False)
        try:
            from sb.briefing import generate_briefing
        except ModuleNotFoundError:
            return StageReport((), 0, 0, 0, False)
        return StageReport((generate_briefing(inputs, _llm(config, llm_mode), config),), 0, 0, int(bool(run_id)), False)

    return stage


def run_ingest(
    config: Config, sources: Sequence[str] | None, *, stage: StageFn | None = None, limit: int | None = None
) -> RunOutcome:
    return _execute(config, stage if stage is not None else _ingest(config, sources, limit))


def run_compile(config: Config, *, compiler: StageFn | None = None, llm_mode: str = "cli") -> RunOutcome:
    return _execute(config, compiler if compiler is not None else _compile_stage(config, llm_mode))


def run_brief(config: Config, *, generator: BriefGenerator | None = None, llm_mode: str = "cli") -> RunOutcome:
    return _execute(config, _brief_stage(config, generator, llm_mode))


def run_all(config: Config) -> RunOutcome:
    root = Path(config.vault_root)
    with _run_lock(root) as acquired:
        if not acquired:
            return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
        ingest = _run_locked(root, _ingest(config, None, None))
        compiled = _run_locked(root, _compile_stage(config, "cli"))
        brief = _run_locked(root, _brief_stage(config, None, "cli"))
        chosen = brief
        for outcome in (ingest, compiled, brief):
            if outcome.exit_code != 0:
                return outcome
            if outcome.status == "capped":
                chosen = outcome
        return chosen


def read_status(config: Config) -> str:
    return read_status_line(Path(config.vault_root)) or "no runs"
