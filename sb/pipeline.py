"""Thin run orchestration: lock, ledger, logs, briefing I/O, vault writes."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from uuid import uuid4

from sb.config import Config
from sb.connectors.base import AcknowledgingSourceAdapter, SourceAdapter
from sb.contracts import Blob, BriefingInputs, PageSpec, SourceRef, Unit
from sb.erasure import ErasureError, IngressIdentity, ReingressGate
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
    generation_runtime_paths,
)
from sb.llm import LLMClient, LLMUnavailable
from sb.page_ids import git_rel
from sb.store import (
    DerivationOutput,
    DerivStatus,
    InvalidDerivationTransition,
    Run,
    RunStage,
    SourceItem,
    UnitRow,
    deriv_key,
)
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, parse_page_frontmatter
from sb.vault import GitCommandError, Vault, VaultLintError, read_page_spec

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
    deriv_key: str | None = None
    written: int = 0
    derivations: tuple[tuple[str, DerivationOutput], ...] = ()
    compiled_by: tuple[str, str] | None = None
    failure: str | None = None


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
    written: int = 0
    failure: str | None = None


class StageFn(Protocol):
    def __call__(self, ledger: Ledger, vault: Vault, run_id: str) -> StageReport: ...


class BriefGenerator(Protocol):
    def __call__(
        self, inputs: BriefingInputs, llm: LLMClient | None, config: Config
    ) -> PageSpec: ...


class _CitedFake:
    def generate(
        self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120
    ) -> str:
        del system, json_mode, timeout
        found: list[str] = _SID.findall(prompt)
        if not found:
            found = re.findall(r"\[\^([0-9a-f]{8})\]", prompt)
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
            if facts is not None and not all(
                self._cas.exists(digest) for _o, digest in facts.sources
            ):
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
    return (
        Path(f"{page_id}.md")
        if page_id.startswith(("conflicts/", "daily/", "wiki/"))
        else Path("wiki") / f"{page_id}.md"
    )


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
        normalized = stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone().date()


def _source_changed(ledger: Ledger, sources: tuple[tuple[str, str], ...]) -> bool:
    items = ledger.list_source_items()
    for origin, digest in sources:
        source_id, _sep, uri = origin.partition(":")
        if any(
            row.content_hash != digest
            for row in items
            if row.source_id == source_id and row.source_uri == uri
        ):
            return True
    return False


def _cite_line(source_id: str, source_uri: str, digest: str, text: str) -> str:
    return f"origin={source_id}:{source_uri} hash={digest} [^{digest[:8]}] text={text}"


def _blob_line(cas: ContentAddressedStore, digest: str, fallback: str) -> str:
    if not cas.exists(digest):
        return fallback
    lines = cas.get(digest).decode("utf-8", errors="replace").splitlines()
    return lines[0].strip() if lines and lines[0].strip() else fallback


def collect_briefing_inputs(
    ledger: Ledger, vault_root: Path, *, today: date | None = None
) -> BriefingInputs:
    """Load K4 briefing inputs from the ledger and tracked vault files."""
    day, root = (datetime.now().astimezone().date() if today is None else today), Path(vault_root)
    yesterday, cas = day - timedelta(days=1), ContentAddressedStore(root)
    y_items = [
        _cite_line(
            item.source_id,
            item.source_uri,
            item.content_hash,
            _blob_line(cas, item.content_hash, item.source_uri),
        )
        for item in ledger.list_source_items()
        if cas.exists(item.content_hash)
        and (run := ledger.get_run(item.first_seen_run)) is not None
        and _as_date(run.started_at) == yesterday
    ]
    open_pages = _conflict_items(root, cas)
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
                stale.append(_stale_item(ledger, facts.page_id, facts.sources))
    start, end = day - UPCOMING_WINDOW, day + UPCOMING_WINDOW
    for item in ledger.list_source_items():
        run = ledger.get_run(item.last_seen_run)
        seen = None if run is None else _as_date(run.started_at)
        if seen is None or seen < start or not cas.exists(item.content_hash):
            continue
        for raw in cas.get(item.content_hash).decode("utf-8", errors="replace").splitlines():
            matched = _ISO_DATE.search(raw)
            if matched is not None and day <= date.fromisoformat(matched.group(0)) <= end:
                upcoming.append(
                    _cite_line(item.source_id, item.source_uri, item.content_hash, raw.strip())
                )
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
    return BriefingInputs(
        tuple(sorted(y_items)), open_pages, tuple(sorted(stale)), tuple(upcoming), last, token
    )


def _stale_item(ledger: Ledger, page_id: str, sources: tuple[tuple[str, str], ...]) -> str:
    for origin, _old in sources:
        source_id, _sep, uri = origin.partition(":")
        for item in ledger.list_source_items():
            if item.source_id == source_id and item.source_uri == uri:
                return _cite_line(source_id, uri, item.content_hash, page_id)
    return page_id


def _conflict_items(root: Path, cas: ContentAddressedStore) -> tuple[str, ...]:
    folder = root / "conflicts"
    if not folder.is_dir():
        return ()
    items: list[str] = []
    for path in folder.glob("*.md"):
        rel = path.relative_to(root).as_posix()
        facts = parse_page_frontmatter(path.read_text(encoding="utf-8"))
        cited = False
        if facts is not None:
            for origin, digest in facts.sources:
                if cas.exists(digest):
                    source_id, _sep, uri = origin.partition(":")
                    items.append(_cite_line(source_id or "conflict", uri or rel, digest, rel))
                    cited = True
                    break
        if not cited:
            items.append(rel)
    return tuple(sorted(items))


def _last_run_line(root: Path) -> str | None:
    path = root / ".sb" / "runs.log"
    lines = (
        [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.is_file()
        else []
    )
    return lines[-1] if lines else None


def _select_adapters(
    chosen: Mapping[str, SourceAdapter], source_ids: Sequence[str] | None, config: Config
) -> list[SourceAdapter]:
    from sb.connectors import discover_adapters

    candidates = list(chosen.items())
    expanded: set[str] = set()
    seen_ids: set[str] = set()
    for row in config.source_roots:
        source_id = row.get("id")
        if not source_id:
            continue
        if source_id in seen_ids:
            raise ValueError("SOURCE_ID_DUPLICATE")
        seen_ids.add(source_id)
        isolated = Config(raw={**config.raw, "sources": [row]}, base_dir=config.base_dir)
        matches = [(key, adapter) for key, adapter in discover_adapters(isolated).items()
                   if adapter.source_id == source_id]
        if len(matches) > 1:
            raise ValueError("SOURCE_ID_AMBIGUOUS")
        if not matches:
            continue
        key, adapter = matches[0]
        if key not in expanded:
            candidates = [(name, item) for name, item in candidates if name != key]
            expanded.add(key)
        candidates.append((key, adapter))
    if source_ids is None:
        return [adapter for _, adapter in candidates]
    names = set(source_ids)
    return [adapter for key, adapter in candidates if key in names or adapter.source_id in names]


def _materialize(data: bytes, digest: str, uri: str, origin: str) -> list[Unit]:
    from sb.normalize import normalize
    from sb.parsers import ParseError, UnsupportedSuffix, parser_for

    path_part = uri.split("#", 1)[0]
    suffix = Path(path_part).suffix.lower()
    if suffix in {".jsonl", ".json"}:
        suffix = ".md"
    try:
        text = parser_for(suffix or ".md")(data)
    except (ParseError, UnsupportedSuffix, UnicodeDecodeError):
        return []
    return normalize(Blob(digest, len(data)), text, origin)


def _unit_rows(units: Sequence[Unit]) -> list[UnitRow]:
    from sb.normalize import NORMALIZER_VERSION

    return [
        UnitRow(
            unit.unit_id,
            unit.content_hash,
            unit.span,
            hashlib.sha256(unit.text.encode()).hexdigest(),
            NORMALIZER_VERSION,
        )
        for unit in units
    ]


def _load_units(ledger: Ledger, root: Path) -> list[Unit]:
    cas = ContentAddressedStore(root)
    loaded: list[Unit] = []
    for item in ledger.list_source_items():
        if cas.exists(item.content_hash):
            loaded.extend(
                _materialize(
                    cas.get(item.content_hash),
                    item.content_hash,
                    item.source_uri,
                    f"{item.source_id}:{item.source_uri}",
                )
            )
    return loaded


def _source_content_ids(ledger: Ledger, root: Path) -> tuple[str, ...]:
    cas = ContentAddressedStore(root)
    return tuple(
        sorted(
            {
                item.content_hash
                for item in ledger.list_source_items()
                if cas.exists(item.content_hash)
            }
        )
    )


def _brief_facts(inputs: BriefingInputs, day: date, content_ids: tuple[str, ...]) -> str:
    from sb.briefing import BRIEFING_RECORD_POLICY

    payload = "\0".join(
        (
            BRIEFING_RECORD_POLICY,
            day.isoformat(),
            *content_ids,
            "\x1e",
            *inputs.open_conflict_pages,
            "\x1e",
            *inputs.stale_pages,
            "\x1e",
            *inputs.upcoming_items,
            "\x1e",
            inputs.last_brief or "",
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _commit_pages(
    root: Path, vault: Vault, run_id: str, report: StageReport, line: str, compiled: _Compiled, *, project: bool = True
) -> tuple[str | None, int, int]:
    result = vault.write_pages(
        report.pages,
        run_id,
        compiled,
        log_line=line,
        compiled_by=report.compiled_by,
    )
    applied = tuple(page for page in report.pages if page.page_id in result.applied_page_ids)
    compiled.remember(applied)
    _register_compiled(root, applied, project=project)
    if result.proposals:
        raise VaultLintError((f"AUTOMATIC_PAGE_UPDATE_CONFLICT: {result.proposals} proposal(s); active pages preserved",))
    return result.commit, result.pages, result.conflicts


def _register_compiled(
    root: Path, pages: Sequence[PageSpec], *, project: bool = True
) -> None:
    if not pages or ".staging" in root.parts:
        return
    from sb.config import load_config
    from sb.knowledge_registry import ACTIVE, APPROVED, KnowledgeRegistry
    from sb.search import SearchIndex, resolve_registry_path

    config = load_config()
    explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
    registry = KnowledgeRegistry(resolve_registry_path(root, explicit))
    for page in pages:
        if page.page_id.startswith("wiki/_proposed/"):
            continue
        registry.put(
            page.page_id,
            knowledge_status=ACTIVE,
            approval_status=APPROVED,
            decided_by="sb-compile",
            reason="ai-first auto ingest",
        )
    if project:
        SearchIndex(vault_root=root, registry_path=explicit).project()


def _finish_deriv(ledger: Ledger, key: str | None, digest: str, path: str) -> None:
    if key is None:
        return
    ledger.mark_done(key, DerivationOutput(digest, path))


def _fail_deriv(ledger: Ledger, key: str | None, error: str) -> None:
    if key is None:
        return
    ledger.mark_failed(key, error)


def _finish_pending(ledger: Ledger, pending: Sequence[tuple[str, DerivationOutput]]) -> None:
    for key, output in pending:
        ledger.mark_done(key, output)


def _fail_pending(
    ledger: Ledger, pending: Sequence[tuple[str, DerivationOutput]], error: str
) -> None:
    for key, _output in pending:
        row = ledger.get_derivation(key)
        if row is not None and row.status == DerivStatus.RUNNING.value:
            ledger.mark_failed(key, error)


def _reopen_failed(ledger: Ledger, key: str) -> None:
    """Return a failed brief key to pending so the same key can mark_running again."""
    row = ledger.get_derivation(key)
    if row is None or row.status != DerivStatus.FAILED.value:
        return
    _ = ledger.requeue_failed(key)


def _append_run_log(root: Path, line: str) -> None:
    log = root / ".sb" / "runs.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        _ = handle.write(line.rstrip() + "\n")


def _run_locked(root: Path, stage: StageFn, stage_name: str) -> RunOutcome:
    run_id, started, vault = uuid4().hex, datetime.now().astimezone().isoformat(), Vault(root=root)
    compiled = _Compiled(root, ContentAddressedStore(root))
    with Ledger(root) as ledger:
        _ = ledger.reset_stale_running(run_id)
        ledger.record_stage(RunStage(run_id, stage_name, started, None, "running", 0, 0, 0))
        try:
            report = stage(ledger, vault, run_id)
        except Exception as exc:  # noqa: BLE001 - stage boundary must persist unexpected failures
            finished = datetime.now(UTC).isoformat()
            detail = f"{type(exc).__name__}: {exc}"
            ledger.record_stage(
                RunStage(run_id, stage_name, started, finished, "failed", 0, 0, 1, detail)
            )
            ledger.record_run(Run(run_id, started, finished, None, "failed"))
            line = f"{started} run {run_id} failed pages=0 conflicts=0 errors=1"
            _append_run_log(root, line)
            return RunOutcome(run_id, "failed", 0, 0, 1, 1, None)
        if report.failure is not None:
            status, exit_code = "failed", 1
        elif report.capped:
            status, exit_code = "capped", 0
        elif report.attempted > 0 and report.errors * 2 > report.attempted:
            status, exit_code = "failed", 1
        elif report.errors > 0:
            status, exit_code = "partial", 0
        else:
            status, exit_code = "ok", 0
        commit, pages, conflicts, errors = None, 0, report.conflicts, report.errors
        rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={{2}}"
        if report.pages:
            try:
                commit, pages, conflicts = _commit_pages(
                    root,
                    vault,
                    run_id,
                    report,
                    rendered.format(len(report.pages), conflicts, errors),
                    compiled,
                )
                _finish_deriv(
                    ledger,
                    report.deriv_key,
                    hashlib.sha256(report.pages[0].body_md.encode()).hexdigest(),
                    f"{report.pages[0].page_id}.md",
                )
                _finish_pending(ledger, report.derivations)
            except (VaultLintError, GitCommandError, OSError) as exc:
                _fail_deriv(ledger, report.deriv_key, str(exc))
                _fail_pending(ledger, report.derivations, str(exc))
                status, exit_code, errors = "failed", 1, max(errors, 1)
        pages = pages or report.written
        if status == "failed":
            rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={{2}}"
        finished = datetime.now(UTC).isoformat()
        ledger.record_run(Run(run_id, started, finished, commit, status))
        ledger.record_stage(
            RunStage(
                run_id,
                stage_name,
                started,
                finished,
                status,
                report.attempted,
                report.written or pages,
                errors,
                report.failure,
            )
        )
        _append_run_log(root, rendered.format(pages, conflicts, errors))
        return RunOutcome(
            run_id, status, pages, conflicts, errors, exit_code, commit, False, report.written,
            report.failure,
        )


def _execute(config: Config, stage: StageFn, stage_name: str) -> RunOutcome:
    root = Path(config.vault_root)
    managed = root.is_symlink() or "share_root" in config.raw
    lock_root = generation_runtime_paths(config).state if managed else root
    fd = _try_lock(lock_root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        if not managed:
            return _run_locked(root, stage, stage_name)
        service = GenerationMutationService.from_config(config)
        try:
            result = service.mutate(GenerationMutation(
                mutation_id=f"pipeline:{stage_name}:{uuid4().hex}",
                operation=GenerationOperation(stage_name), now=datetime.now(UTC),
                authority=GenerationAuthority(None, None),
                apply=lambda staging: _run_locked(staging, stage, stage_name),
            ))
            return replace(result.value, git_commit=result.generation.head if result.value.git_commit else None)
        finally:
            service.close()
    finally:
        _unlock(fd)



@dataclass(frozen=True, slots=True)
class _PreparedIngest:
    source_items: tuple[SourceItem, ...]
    units: tuple[UnitRow, ...]
    version_keys: tuple[tuple[str, str, str], ...]
    errors: int
    attempted: int
    written: int
    capped: bool
    cursor: tuple[str, str] | None
    failure: str | None


def _prepare_adapter_ingest(
    adapter: SourceAdapter,
    ledger: Ledger,
    cas: ContentAddressedStore,
    seen: set[tuple[str, str, str]],
    run_id: str,
    remaining: int,
    reingress: ReingressGate,
    unit_remaining: int,
    unit_cap: int,
) -> _PreparedIngest:
    items = adapter.scan(ledger.get_cursor(adapter.source_id))
    source_items: list[SourceItem] = []
    unit_rows: list[UnitRow] = []
    version_keys: list[tuple[str, str, str]] = []
    accepted: set[tuple[str, str, str]] = set()
    allocated_units: set[str] = set()
    failure: str | None = None
    errors = attempted = written = 0
    capped = adapter_failed = False
    for ref, data, meta in items:
        version_key = (ref.source_id, ref.source_uri, ref.source_version)
        if version_key in seen or version_key in accepted:
            continue
        if attempted >= remaining:
            capped = True
            break
        attempted += 1
        if meta.get("skip_reason"):
            skip_digest = hashlib.sha256(f"skip:{ref.source_version}".encode()).hexdigest()
            source_items.append(
                SourceItem(
                    ref.source_id,
                    ref.source_uri,
                    ref.source_version,
                    skip_digest,
                    run_id,
                    run_id,
                )
            )
            version_keys.append(version_key)
            accepted.add(version_key)
            continue
        digest = hashlib.sha256(data).hexdigest()
        try:
            reingress.check(IngressIdentity(source=ref.source_id, content=digest))
            reingress.check_content(data)
        except ErasureError:
            adapter_failed = True
            continue
        units = _materialize(
            data,
            digest,
            ref.source_uri,
            f"{ref.source_id}:{ref.source_uri}",
        )
        new_units = [unit for unit in units
                     if unit.unit_id not in allocated_units and ledger.get_unit(unit.unit_id) is None]
        if len(new_units) > unit_cap:
            errors += 1
            adapter_failed = True
            failure = failure or (
                f"INGEST_UNIT_BUDGET_EXCEEDED: source requires {len(new_units)} new units; "
                f"caps.max_new_units_per_run={unit_cap}. Source retained; "
                "increase the configured budget or split the source before retrying."
            )
            continue
        if len(new_units) > unit_remaining - len(allocated_units):
            capped = True
            continue
        try:
            _ = cas.put(data)
        except OSError:
            errors += 1
            adapter_failed = True
            continue
        source_items.append(
            SourceItem(
                ref.source_id,
                ref.source_uri,
                ref.source_version,
                digest,
                run_id,
                run_id,
            )
        )
        unit_rows.extend(_unit_rows(new_units))
        allocated_units.update(unit.unit_id for unit in new_units)
        version_keys.append(version_key)
        accepted.add(version_key)
        if units or not data:
            written += 1
    cursor: tuple[str, str] | None = None
    if not capped and not adapter_failed and (version_keys or attempted == 0):
        cursor = (adapter.next_cursor(), datetime.now(UTC).isoformat())
    return _PreparedIngest(
        tuple(source_items),
        tuple(unit_rows),
        tuple(version_keys),
        errors,
        attempted,
        written,
        capped,
        cursor,
        failure,
    )


def _ingest(config: Config, source_ids: Sequence[str] | None, limit: int | None) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        from sb.connectors import discover_adapters

        source_config = Config(raw={**config.raw, "vault_root": str(vault.root)}, base_dir=config.base_dir)
        try:
            classifications = config.source_access
            for item in ledger.list_source_items():
                configured = classifications.get(item.source_id)
                existing = ledger.source_access_for(item) if configured is not None else None
                if existing is not None and existing != configured:
                    return StageReport((), 0, 1, 0, False, failure="SOURCE_ACCESS_RECLASSIFICATION_REQUIRED")
        except ValueError as exc:
            return StageReport((), 0, 1, 0, False, failure=str(exc))
        chosen = discover_adapters(source_config)
        try:
            adapters = _select_adapters(chosen, source_ids, source_config)
        except ValueError as exc:
            return StageReport((), 0, 1, 0, False, failure=str(exc))
        cas = ContentAddressedStore(vault.root)
        cap = config.caps["max_source_items_per_run"] if limit is None else limit
        unit_cap = config.caps["max_new_units_per_run"]
        if cap < 0 or unit_cap < 0:
            return StageReport((), 0, 1, 0, False,
                               failure="INGEST_BUDGET_INVALID: budgets must be nonnegative")
        seen = {
            (item.source_id, item.source_uri, item.source_version)
            for item in ledger.list_source_items()
        }
        errors = attempted = written = 0
        capped = False
        used_units = 0
        failure: str | None = None
        for adapter in adapters:
            try:
                reingress = ReingressGate(Path(config.state_root) / "reingress.db")
                try:
                    prepared = _prepare_adapter_ingest(
                        adapter,
                        ledger,
                        cas,
                        seen,
                        run_id,
                        max(cap - attempted, 0),
                        reingress,
                        unit_cap - used_units,
                        unit_cap,
                    )
                finally:
                    reingress.close()
            except (OSError, RuntimeError):
                errors += 1
                attempted += 1
                continue
            with ledger.transaction():
                _ = ledger.upsert_source_items(prepared.source_items)
                classification = classifications.get(adapter.source_id)
                if classification is not None:
                    for item in prepared.source_items:
                        ledger.bind_source_access(item, classification)
                _ = ledger.upsert_units(prepared.units)
                if prepared.cursor is not None:
                    position, updated_at = prepared.cursor
                    ledger.set_cursor(adapter.source_id, position, updated_at)
            if isinstance(adapter, AcknowledgingSourceAdapter):
                try:
                    adapter.acknowledge(tuple(
                        SourceRef(item.source_id, item.source_uri, item.source_version)
                        for item in ledger.list_source_items()
                        if item.source_id == adapter.source_id
                        and cas.exists(item.content_hash)
                    ))
                except OSError:
                    errors += 1
            seen.update(prepared.version_keys)
            used_units += len(prepared.units)
            errors += prepared.errors
            attempted += prepared.attempted
            written += prepared.written
            capped = capped or prepared.capped
            failure = failure or prepared.failure
            if capped and attempted >= cap:
                break
        return StageReport((), 0, errors, attempted, capped, None, written, failure=failure)

    return stage


def _llm(config: Config, llm_mode: str) -> LLMClient:
    from sb.llm import CliLLM

    return _CitedFake() if llm_mode == "fake" else CliLLM(list(config.llm.argv_template))


def _page_ready(root: Path, page: PageSpec) -> bool:
    known = {cite.sid for cite in page.sources}
    for match in re.finditer(r"\[\^([^\]]+)\]", page.body_md):
        if match.group(1) not in known:
            return False
    return all(
        len(cite.hash) == 64 and (root / "raw" / cite.hash[:2] / cite.hash).is_file()
        for cite in page.sources
    )


def _compile_stage(config: Config, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        try:
            from sb.compile import PendingCompile, compile_pending, page_id_for_origin
        except ModuleNotFoundError:
            return StageReport((), 0, 0, 0, False)
        units = _load_units(ledger, vault.root)
        llm = _llm(config, llm_mode)
        existing: dict[str, PageSpec] = {}
        for page_id in sorted({page_id_for_origin(unit.origin) for unit in units}):
            page = read_page_spec(vault.root, page_id)
            if page is not None:
                existing[page_id] = page
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        committed_pages: list[PageSpec] = []
        write_errors = 0

        def on_page(item: PendingCompile) -> None:
            nonlocal write_errors
            page = item.page
            if not _page_ready(vault.root, page):
                ledger.mark_failed(item.key, "compile page failed citation readiness")
                write_errors += 1
                return
            previous_path = vault.root / git_rel(page.page_id)
            previous_digest = ("sha256:" + hashlib.sha256(previous_path.read_bytes()).hexdigest()
                if previous_path.is_file() else None)
            parent = ledger.page_access_for(git_rel(page.page_id).removesuffix(".md"), previous_digest) if previous_digest is not None else None
            access = ledger.compiled_page_access(item.input_sources,
                parent, unknown_parent=item.untracked_context or (previous_digest is not None and parent is None))
            single = StageReport(
                (page,),
                0,
                0,
                1,
                False,
                compiled_by=(config.llm.prompt_version, config.llm.model_id),
            )
            try:
                committed, _, _ = _commit_pages(
                    vault.root,
                    vault,
                    run_id,
                    single,
                    f"{run_id} compile {page.page_id}",
                    compiled,
                    project=False,
                )
            except (VaultLintError, GitCommandError, OSError) as exc:
                ledger.mark_failed(item.key, str(exc))
                write_errors += 1
                return
            try:
                raw = subprocess.check_output(["git", "-C", str(vault.root), "show",
                    f"{committed or 'HEAD'}:{git_rel(page.page_id)}"])
                ledger.bind_page_access(git_rel(page.page_id).removesuffix(".md"), "sha256:" + hashlib.sha256(raw).hexdigest(), access)
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                ledger.mark_failed(item.key, str(exc))
                write_errors += 1
                return
            ledger.mark_done(item.key, item.output)
            committed_pages.append(page)

        def on_error(_exc: LLMUnavailable) -> None:
            nonlocal write_errors
            write_errors += 1

        pending, capped = compile_pending(
            units,
            ledger,
            llm,
            config,
            existing_pages=existing,
            on_page=on_page,
            on_error=on_error,
        )
        committed_ids = {page.page_id for page in committed_pages}
        leftover = [item for item in pending if item.page.page_id not in committed_ids]
        kept = committed_pages + [item.page for item in leftover]
        derivations = [(item.key, item.output) for item in leftover]
        errors = write_errors
        checker = None
        try:
            from sb.conflict import check as checker
        except ModuleNotFoundError:
            checker = None
        if checker is not None:
            for finding in checker(units, kept, ledger, llm, config, finalize=False):
                page = finding.page
                deriv = (
                    (finding.deriv_key, finding.deriv_output)
                    if finding.deriv_key is not None and finding.deriv_output is not None
                    else None
                )
                if page is None:
                    if deriv is not None:
                        ledger.mark_done(deriv[0], deriv[1])
                    continue
                if _page_ready(vault.root, page):
                    kept.append(page)
                    if deriv is not None:
                        derivations.append(deriv)
                    continue
                errors += 1
                if deriv is not None:
                    row = ledger.get_derivation(deriv[0])
                    if row is not None and row.status == DerivStatus.RUNNING.value:
                        ledger.mark_failed(deriv[0], "conflict page failed citation readiness")
        if committed_pages and ".staging" not in vault.root.parts:
            from sb.config import load_config as _load_cfg
            from sb.search import SearchIndex

            cfg = _load_cfg()
            explicit = Path(cfg.knowledge_registry) if "knowledge_registry" in cfg.raw else None
            SearchIndex(vault_root=vault.root, registry_path=explicit).project()
        return StageReport(
            tuple(page for page in kept if page.page_id not in committed_ids),
            sum(1 for page in kept if page.page_id.startswith("conflicts/")),
            errors,
            max(len(kept) + errors, int(bool(run_id))),
            capped,
            written=len(committed_pages),
            derivations=tuple(derivations),
            compiled_by=(config.llm.prompt_version, config.llm.model_id),
        )

    return stage


def _brief_stage(config: Config, generator: BriefGenerator | None, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        day = datetime.now().astimezone().date()
        inputs = collect_briefing_inputs(ledger, vault.root, today=day)
        key = deriv_key(
            (_brief_facts(inputs, day, _source_content_ids(ledger, vault.root)),),
            "brief",
            config.llm.prompt_version,
            config.llm.model_id,
        )
        existing = ledger.get_derivation(key)
        if existing is not None and existing.status == DerivStatus.DONE.value:
            return StageReport((), 0, 0, 0, False)
        if existing is not None and existing.status == DerivStatus.FAILED.value:
            _reopen_failed(ledger, key)
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
        page = replace(
            page,
            prompt_version=config.llm.prompt_version,
            model_id=config.llm.model_id,
            derivation_key=key,
        )
        return StageReport(
            (page,),
            0,
            0,
            1,
            False,
            key,
            compiled_by=(config.llm.prompt_version, config.llm.model_id),
        )

    return stage


def run_ingest(
    config: Config,
    sources: Sequence[str] | None,
    *,
    stage: StageFn | None = None,
    limit: int | None = None,
) -> RunOutcome:
    return _execute(
        config, stage if stage is not None else _ingest(config, sources, limit), "ingest"
    )


def run_compile(
    config: Config, *, compiler: StageFn | None = None, llm_mode: str = "cli"
) -> RunOutcome:
    return _execute(
        config,
        compiler if compiler is not None else _compile_stage(config, llm_mode),
        "compile",
    )


def run_brief(
    config: Config, *, generator: BriefGenerator | None = None, llm_mode: str = "cli"
) -> RunOutcome:
    return _execute(config, _brief_stage(config, generator, llm_mode), "brief")


def run_all(config: Config, sources: Sequence[str] | None = None) -> RunOutcome:
    root = Path(config.vault_root)
    if not root.is_symlink() and "share_root" not in config.raw:
        return _run_all_mutable(config, sources)
    lock_root = generation_runtime_paths(config).state
    fd = _try_lock(lock_root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        service = GenerationMutationService.from_config(config)
        try:
            def staged(root: Path) -> RunOutcome:
                raw = {**config.raw, "vault_root": str(root)}
                return _run_all_mutable(Config(raw=raw, base_dir=config.base_dir), sources)
            result = service.mutate(GenerationMutation(
                mutation_id=f"pipeline:run:{uuid4().hex}", operation=GenerationOperation.RUN,
                now=datetime.now(UTC), authority=GenerationAuthority(None, None), apply=staged,
            ))
            return replace(result.value, git_commit=result.generation.head if result.value.git_commit else None)
        finally:
            service.close()
    finally:
        _unlock(fd)


def _run_all_mutable(config: Config, sources: Sequence[str] | None = None) -> RunOutcome:
    root = Path(config.vault_root)
    fd = _try_lock(root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        ingest = _run_locked(root, _ingest(config, sources, None), "ingest")
        compiled = _run_locked(root, _compile_stage(config, "cli"), "compile")
        if ingest.written == 0 and compiled.pages == 0:
            brief = compiled if compiled.exit_code == 0 else ingest
            if ingest.status == "capped" and ingest.exit_code == 0:
                brief = ingest
        else:
            brief = _run_locked(root, _brief_stage(config, None, "cli"), "brief")
    finally:
        _unlock(fd)
    chosen = brief
    for outcome in (ingest, compiled, brief):
        if outcome.exit_code != 0:
            return outcome
        if outcome.status == "capped":
            chosen = outcome
    if brief.exit_code == 0 and (
        brief.status == "capped"
        or (ingest.status != "capped" and compiled.status != "capped")
    ):
        chosen = brief
    return chosen


def read_status(config: Config) -> str:
    return _last_run_line(Path(config.vault_root)) or "no runs"


def audit_citations(root: Path) -> tuple[str, ...]:
    """Return unresolved K1 citation reasons for tracked wiki/daily/conflicts pages."""
    reasons: list[str] = []
    for folder in ("wiki", "daily", "conflicts"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if "_proposed" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            facts = parse_page_frontmatter(text)
            known = {digest[:8] for _origin, digest in (facts.sources if facts is not None else ())}
            if facts is not None:
                for _origin, digest in facts.sources:
                    if len(digest) != 64 or not (root / "raw" / digest[:2] / digest).is_file():
                        reasons.append(f"{path.relative_to(root).as_posix()}: missing CAS {digest}")
            body = text.split("---", 2)[-1] if text.startswith("---") else text
            for match in re.finditer(r"\[\^([^\]]+)\]", body):
                sid = match.group(1)
                if sid not in known:
                    reasons.append(f"{path.relative_to(root).as_posix()}: unresolved [^{sid}]")
    return tuple(reasons)
