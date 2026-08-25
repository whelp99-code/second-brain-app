"""Thin run orchestration: lock, ledger, logs, briefing I/O, vault writes."""
# noqa: SIZE_OK — single owned orchestrator; ownership forbids a split

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from uuid import uuid4

from sb.config import Config
from sb.contracts import Blob, BriefingInputs, PageSpec, Unit
from sb.llm import LLMClient, LLMUnavailable
from sb.store import (
    DerivationOutput,
    DerivStatus,
    InvalidDerivationTransition,
    Run,
    SourceItem,
    UnitRow,
    deriv_key,
)
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, parse_page_frontmatter
from sb.vault import Vault

STALE_AFTER: Final = timedelta(days=30)
UPCOMING_WINDOW: Final = timedelta(days=7)
_UPDATED: Final = re.compile(r"^updated:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_SID: Final = re.compile(r"\bsid=([0-9a-f]{8})\b")


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


class _CitedFake:
    def generate(self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120) -> str:
        del system, json_mode, timeout
        found: list[str] = _SID.findall(prompt)
        return " ".join(f"Cited.[^{sid}]" for sid in dict.fromkeys(found)) or "empty."


class _Compiled:
    _root: Path
    _cas: ContentAddressedStore
    _dir: Path

    def __init__(self, root: Path, cas: ContentAddressedStore) -> None:
        self._root, self._cas, self._dir = root, cas, root / ".sb" / "compiled"

    def last_compiled_hash(self, page_id: str) -> str | None:
        stored = self._dir / f"{page_id.replace('/', '_')}.sha"
        dest = self._root / _dest(page_id)
        if not stored.is_file():
            return None
        if dest.is_file():
            facts = parse_page_frontmatter(dest.read_text(encoding="utf-8"))
            if facts is not None and not all(self._cas.exists(digest) for _o, digest in facts.sources):
                return None
        return stored.read_text(encoding="utf-8").strip()

    def remember(self, pages: Sequence[PageSpec]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            dest = self._root / _dest(page.page_id)
            if dest.is_file():
                _ = (self._dir / f"{page.page_id.replace('/', '_')}.sha").write_text(
                    hashlib.sha256(dest.read_bytes()).hexdigest(), encoding="utf-8"
                )


def _dest(page_id: str) -> Path:
    return Path(f"{page_id}.md") if page_id.startswith(("conflicts/", "daily/", "wiki/")) else Path("wiki") / f"{page_id}.md"


def _try_lock(root: Path) -> int | None:
    path = root / ".sb" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _unlock(fd: int) -> None:
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
        if any(row.content_hash != digest for row in items if row.source_id == source_id and row.source_uri == uri):
            return True
    return False


def collect_briefing_inputs(ledger: Ledger, vault_root: Path, *, today: date | None = None) -> BriefingInputs:
    """Load K4 briefing inputs from the ledger and tracked vault files."""
    day, root = (datetime.now(UTC).date() if today is None else today), Path(vault_root)
    yesterday, cas = day - timedelta(days=1), ContentAddressedStore(root)
    y_items = [
        f"{item.source_id}:{item.source_uri}"
        for item in ledger.list_source_items()
        if (run := ledger.get_run(item.first_seen_run)) is not None and _as_date(run.started_at) == yesterday
    ]
    open_pages = (
        () if not (root / "conflicts").is_dir()
        else tuple(sorted(path.relative_to(root).as_posix() for path in (root / "conflicts").glob("*.md")))
    )
    stale: list[str] = []
    upcoming: list[str] = []
    dailies: list[tuple[date, Path]] = []
    if (root / "wiki").is_dir():
        cutoff = day - STALE_AFTER
        for path in (root / "wiki").rglob("*.md"):
            if "_proposed" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            matched, facts = _UPDATED.search(text), parse_page_frontmatter(text)
            if matched is None or date.fromisoformat(matched.group(1)) > cutoff or facts is None:
                continue
            if _source_changed(ledger, facts.sources):
                stale.append(facts.page_id)
    start, end = day - UPCOMING_WINDOW, day + UPCOMING_WINDOW
    for item in ledger.list_source_items():
        run = ledger.get_run(item.last_seen_run)
        seen = None if run is None else _as_date(run.started_at)
        if seen is None or seen < start or not cas.exists(item.content_hash):
            continue
        for raw in cas.get(item.content_hash).decode("utf-8", errors="replace").splitlines():
            matched = _ISO_DATE.search(raw)
            if matched is not None and day <= date.fromisoformat(matched.group(0)) <= end:
                upcoming.append(raw.strip())
    if (root / "daily").is_dir():
        for candidate in (root / "daily").glob("*.md"):
            try:
                stamp = date.fromisoformat(candidate.stem)
            except ValueError:
                continue
            if stamp < day:
                dailies.append((stamp, candidate))
    last = max(dailies)[1].read_text(encoding="utf-8") if dailies else None
    line = _last_run_line(root)
    token = None if line is None or len(line.split()) < 4 else line.split()[3]
    return BriefingInputs(tuple(sorted(y_items)), open_pages, tuple(sorted(stale)), tuple(upcoming), last, token)


def _last_run_line(root: Path) -> str | None:
    path = root / ".sb" / "runs.log"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    return lines[-1] if lines else None


def _materialize(data: bytes, digest: str, uri: str, origin: str) -> list[Unit]:
    from sb.normalize import normalize
    from sb.parsers import ParseError, UnsupportedSuffix, parser_for

    try:
        text = parser_for(Path(uri).suffix or ".md")(data)
    except (ParseError, UnsupportedSuffix, UnicodeDecodeError):
        return []
    return normalize(Blob(digest, len(data)), text, origin)


def _store_units(ledger: Ledger, units: Sequence[Unit]) -> None:
    from sb.normalize import NORMALIZER_VERSION

    for unit in units:
        ledger.upsert_unit(UnitRow(
            unit.unit_id, unit.content_hash, unit.span, hashlib.sha256(unit.text.encode()).hexdigest(), NORMALIZER_VERSION
        ))


def _load_units(ledger: Ledger, root: Path) -> list[Unit]:
    cas = ContentAddressedStore(root)
    loaded: list[Unit] = []
    for item in ledger.list_source_items():
        if cas.exists(item.content_hash):
            loaded.extend(_materialize(
                cas.get(item.content_hash), item.content_hash, item.source_uri, f"{item.source_id}:{item.source_uri}"
            ))
    return loaded


def _brief_facts(inputs: BriefingInputs) -> str:
    payload = "\0".join((
        *inputs.yesterday_items, "\x1e", *inputs.open_conflict_pages, "\x1e",
        *inputs.stale_pages, "\x1e", *inputs.upcoming_items, "\x1e",
        inputs.previous_run_status or "",
    ))
    return hashlib.sha256(payload.encode()).hexdigest()


def _commit_pages(root: Path, vault: Vault, run_id: str, report: StageReport, line: str, compiled: _Compiled) -> tuple[str | None, int, int]:
    del root
    result = vault.write_pages(report.pages, run_id, compiled, log_line=line)
    compiled.remember(report.pages)
    return result.commit, result.pages, result.conflicts


def _run_locked(root: Path, stage: StageFn) -> RunOutcome:
    run_id, started, vault = uuid4().hex, datetime.now(UTC).isoformat(), Vault(root=root)
    compiled = _Compiled(root, ContentAddressedStore(root))
    with Ledger(root) as ledger:
        _ = ledger.reset_stale_running(run_id)
        report = stage(ledger, vault, run_id)
        status, exit_code = ("capped", 0) if report.capped else (
            ("failed", 1) if report.attempted > 0 and report.errors * 2 > report.attempted else ("ok", 0)
        )
        commit, pages, conflicts = None, 0, report.conflicts
        rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={report.errors}"
        if report.pages:
            commit, pages, conflicts = _commit_pages(
                root, vault, run_id, report, rendered.format(len(report.pages), conflicts), compiled
            )
        ledger.record_run(Run(run_id, started, datetime.now(UTC).isoformat(), commit, status))
        log = root / ".sb" / "runs.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            _ = handle.write(rendered.format(pages, conflicts) + "\n")
        return RunOutcome(run_id, status, pages, conflicts, report.errors, exit_code, commit)


def _execute(config: Config, stage: StageFn) -> RunOutcome:
    root = Path(config.vault_root)
    fd = _try_lock(root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        return _run_locked(root, stage)
    finally:
        _unlock(fd)


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
                    units = _materialize(data, digest, ref.source_uri, f"{ref.source_id}:{ref.source_uri}")
                    if not units and data:
                        errors += 1
                        continue
                    ledger.upsert_source_item(SourceItem(
                        ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id
                    ))
                    _store_units(ledger, units)
                    written += 1
                except OSError:
                    errors += 1
            if capped:
                break
            ledger.set_cursor(adapter.source_id, adapter.next_cursor(), datetime.now(UTC).isoformat())
        return StageReport((), 0, errors, attempted, capped)

    return stage


def _llm(config: Config, llm_mode: str) -> LLMClient:
    from sb.llm import CliLLM

    return _CitedFake() if llm_mode == "fake" else CliLLM(list(config.llm.argv_template))


def _compile_stage(config: Config, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        try:
            from sb.compile import compile_pages
        except ModuleNotFoundError:
            return StageReport((), 0, 0, 0, False)
        pages = list(compile_pages(_load_units(ledger, vault.root), ledger, _llm(config, llm_mode), config))
        capped = bool(pages) and pages[-1].status == "CAPPED"
        kept = pages[:-1] if capped else pages
        return StageReport(tuple(kept), 0, 0, max(len(pages), int(bool(run_id))), capped)

    return stage


def _brief_stage(config: Config, generator: BriefGenerator | None, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        inputs = collect_briefing_inputs(ledger, vault.root)
        key = deriv_key((_brief_facts(inputs),), "brief", config.llm.prompt_version, config.llm.model_id)
        existing = ledger.get_derivation(key)
        if existing is not None and existing.status == DerivStatus.DONE.value:
            return StageReport((), 0, 0, 0, False)
        ledger.ensure_derivation(key, "brief", run_id)
        try:
            ledger.mark_running(key, run_id)
        except InvalidDerivationTransition:
            return StageReport((), 0, 1, 1, False)
        try:
            if generator is not None:
                page = generator(inputs, None, config)
            else:
                from sb.briefing import generate_briefing

                page = generate_briefing(inputs, _llm(config, llm_mode), config)
        except (LLMUnavailable, ModuleNotFoundError) as exc:
            ledger.mark_failed(key, str(exc))
            return StageReport((), 0, 1, 1, False)
        ledger.mark_done(key, DerivationOutput(hashlib.sha256(page.body_md.encode()).hexdigest(), f"{page.page_id}.md"))
        return StageReport((page,), 0, 0, 1, False)

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
    fd = _try_lock(root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        ingest = _run_locked(root, _ingest(config, None, None))
        compiled = _run_locked(root, _compile_stage(config, "cli"))
        brief = _run_locked(root, _brief_stage(config, None, "cli"))
    finally:
        _unlock(fd)
    chosen = brief
    for outcome in (ingest, compiled, brief):
        if outcome.exit_code != 0:
            return outcome
        if outcome.status == "capped":
            chosen = outcome
    return chosen


def read_status(config: Config) -> str:
    return _last_run_line(Path(config.vault_root)) or "no runs"
