"""Thin run orchestration: lock, ledger, logs, briefing I/O, vault writes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from uuid import uuid4

from sb.bound_knowledge import BoundKnowledge
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
_RETRYABLE_READ_FAILURES: Final = frozenset({
    "size-limit", "database-limit", "unstable-session-file", "unreadable-session-file",
})


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
        del system, timeout
        if json_mode:
            return json.dumps({"relation": "unrelated", "confidence": 0.0,
                               "rationale": "fake mode: no semantic judgment", "cites": []})
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
            if matched is None:
                continue
            # Source text is arbitrary: a date-shaped run of digits need not be a
            # date. `2026-02-30` in one ingested note took the whole brief stage
            # down with it, so a match that will not parse is simply not a date.
            try:
                upcoming_day = date.fromisoformat(matched.group(0))
            except ValueError:
                continue
            if day <= upcoming_day <= end:
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
        declared = row.get("adapter") or row.get("type") or ""
        matches = [(key, adapter) for key, adapter in discover_adapters(isolated).items()
                   if adapter.source_id == source_id and
                   (not declared or declared in getattr(adapter, "accepted_adapters", (key,)))]
        if len(matches) > 1:
            raise ValueError("SOURCE_ID_AMBIGUOUS")
        if not matches:
            raise ValueError("SOURCE_NOT_FOUND: " + source_id)
        key, adapter = matches[0]
        if key not in expanded:
            candidates = [(name, item) for name, item in candidates if name != key]
            expanded.add(key)
        candidates.append((key, adapter))
    if source_ids is None:
        if "sources" in config.raw:
            return [adapter for _, adapter in candidates if adapter.source_id in seen_ids]
        return [adapter for _, adapter in candidates]
    names = set(source_ids)
    available = {name for key, adapter in candidates for name in (key, adapter.source_id)}
    missing = names - available
    if missing:
        raise ValueError("SOURCE_NOT_FOUND: " + ", ".join(sorted(missing)))
    return [adapter for key, adapter in candidates if key in names or adapter.source_id in names]


# A source URI is not always a filesystem path. unified-db addresses a row as
# `unified-db:<project>:<table>:<row>`, whose dotted table name otherwise reads as
# a file extension (".events:evt_...") that routes to no parser, so the row is
# stored but never becomes a unit. A scheme prefix marks an identifier that is not
# a path, so it carries no suffix; every path-shaped URI keeps its own, which is
# what leaves a genuinely unsupported file (.png, .unsupported) skipped rather
# than parsed as text.
_URI_SCHEME: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")


def _materialize(data: bytes, digest: str, uri: str, origin: str) -> list[Unit]:
    from sb.normalize import normalize
    from sb.parsers import ParseError, UnsupportedSuffix, parser_for

    path_part = uri.split("#", 1)[0]
    suffix = "" if _URI_SCHEME.match(path_part) else Path(path_part).suffix.lower()
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
    root: Path, vault: Vault, run_id: str, report: StageReport, line: str, compiled: _Compiled, *, ledger: Ledger, project: bool = True, config: Config | None = None
) -> tuple[str | None, int, int]:
    result = vault.write_pages(
        report.pages,
        run_id,
        compiled,
        log_line=line,
        compiled_by=report.compiled_by,
    )
    applied = tuple(page for page in report.pages if page.page_id in result.applied_page_ids)
    try:
        with ledger.transaction():
            for page in applied:
                relative = git_rel(page.page_id)
                raw = subprocess.check_output(["git", "-C", str(root), "show",
                    f"{result.commit or 'HEAD'}:{relative}"], stderr=subprocess.PIPE)
                ledger.bind_knowledge(BoundKnowledge(relative.removesuffix(".md"),
                    "sha256:" + hashlib.sha256(raw).hexdigest(), "ACTIVE", "APPROVED"))
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise VaultLintError(("COMPILED_KNOWLEDGE_BINDING_FAILED",)) from exc
    compiled.remember(applied)
    _register_compiled(root, applied, project=project, config=config)
    if result.proposals:
        raise VaultLintError((f"AUTOMATIC_PAGE_UPDATE_CONFLICT: {result.proposals} proposal(s); active pages preserved",))
    return result.commit, result.pages, result.conflicts


def _register_compiled(
    root: Path, pages: Sequence[PageSpec], *, project: bool = True, config: Config | None = None
) -> None:
    if not pages or ".staging" in root.parts:
        return
    from sb.config import load_config
    from sb.knowledge_registry import ACTIVE, APPROVED, KnowledgeRegistry
    from sb.search import SearchIndex, resolve_registry_path

    config = config if config is not None else load_config()
    explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
    registry = KnowledgeRegistry(resolve_registry_path(root, explicit))
    for page in pages:
        if page.page_id.startswith("wiki/_proposed/"):
            continue
        _ = registry.put(
            git_rel(page.page_id).removesuffix(".md"),
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


def _reopen_failed(ledger: Ledger, key: str, max_attempts: int) -> bool:
    """Return a failed or superseded brief key to pending so mark_running can run."""
    row = ledger.get_derivation(key)
    if row is None or row.status not in {
        DerivStatus.FAILED.value, DerivStatus.SUPERSEDED.value,
    }:
        return True
    return ledger.requeue_failed(key, max_attempts=max_attempts)


def _append_run_log(root: Path, line: str) -> None:
    log = root / ".sb" / "runs.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        _ = handle.write(line.rstrip() + "\n")


def _run_locked(root: Path, stage: StageFn, stage_name: str, config: Config | None = None) -> RunOutcome:
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
            return RunOutcome(run_id, "failed", 0, 0, 1, 1, None, failure=detail)
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
                    ledger=ledger,
                    config=config,
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
    from sb.life_lock import VaultPublicationBusy, publication_lock
    try:
        with publication_lock(Path(config.vault_root)):
            return _execute_under_publication_lock(config, stage, stage_name)
    except VaultPublicationBusy:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)


def _execute_under_publication_lock(config: Config, stage: StageFn, stage_name: str) -> RunOutcome:
    root = Path(config.vault_root)
    managed = root.is_symlink() or "share_root" in config.raw
    lock_root = generation_runtime_paths(config).state if managed else root
    fd = _try_lock(lock_root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    try:
        if not managed:
            return _run_locked(root, stage, stage_name, config)
        service = GenerationMutationService.from_config(config)
        try:
            result = service.mutate(GenerationMutation(
                mutation_id=f"pipeline:{stage_name}:{uuid4().hex}",
                operation=GenerationOperation(stage_name), now=datetime.now(UTC),
                authority=GenerationAuthority(None, None),
                apply=lambda staging: _run_locked(staging, stage, stage_name, config),
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
        # A source configuration hold is not a deduplicated/quarantined item.
        # Recheck it on every run, even if older versions recorded a skip row.
        if meta.get("skip_reason") == "ambiguous-session-roots":
            errors += 1
            attempted += 1
            adapter_failed = True
            failure = "SOURCE_ROOTS_AMBIGUOUS"
            break
        reason = meta.get("skip_reason")
        if reason in _RETRYABLE_READ_FAILURES:
            if attempted >= remaining:
                capped = True
                break
            attempted += 1
            errors += 1
            adapter_failed = True
            failure = failure or f"SOURCE_READ_INCOMPLETE: {adapter.source_id}: {reason}"
            continue
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
        except ErasureError as exc:
            adapter_failed = True
            if str(exc) != "TOMBSTONE_REINGRESS_BLOCKED":
                errors += 1
                failure = failure or "REINGRESS_VERIFICATION_FAILED"
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


def _note_source_unavailable(
    ledger: Ledger, root: Path, source_id: str, run_id: str, exc: Exception
) -> None:
    code = type(exc).__name__
    digest = hashlib.sha256(f"SOURCE_UNAVAILABLE:{source_id}:{code}".encode()).hexdigest()
    with ledger.transaction():
        _ = ledger.upsert_source_items(
            (
                SourceItem(
                    source_id,
                    "connection-unavailable",
                    code,
                    digest,
                    run_id,
                    run_id,
                ),
            )
        )
    _append_run_log(root, f"SOURCE_UNAVAILABLE: {source_id}: {code}")


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
            if getattr(adapter, "supports_life_events", False):
                from sb.life_ingest import complete_exports, prepare_exports
                try:
                    life_result = prepare_exports(config, ledger, adapter, run_id=run_id,
                        now=datetime.now(UTC), maximum=max(cap - attempted, 0))
                    life_written = _publish_life_events(config, ledger, vault, run_id, life_result.events)
                    complete_exports(ledger, adapter, life_result, config=config, now=datetime.now(UTC))
                    errors += life_result.errors
                    attempted += life_result.attempted
                    written += life_written
                    capped = capped or life_result.capped
                    if life_result.errors:
                        failure = failure or "LIFE_EXPORT_PARTIAL_FAILURE"
                except (OSError, ValueError, RuntimeError, GitCommandError, VaultLintError) as exc:
                    errors += 1
                    attempted += 1
                    failure = failure or "LIFE_EXPORT_FAILED"
                    _note_source_unavailable(ledger, vault.root, adapter.source_id, run_id, exc)
                if capped and attempted >= cap:
                    break
                continue
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
            except Exception as exc:  # noqa: BLE001 - one unreachable source must not abort the batch
                errors += 1
                attempted += 1
                _note_source_unavailable(ledger, vault.root, adapter.source_id, run_id, exc)
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
                    failure = failure or "SOURCE_ACKNOWLEDGEMENT_FAILED"
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
                    ledger=ledger,
                    project=False,
                    config=config,
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
            def conflict_limit_reached() -> None:
                nonlocal capped
                capped = True

            # Cached compilation must not remove pages needed to retry a failed
            # conflict judgment. Fresh page bodies take precedence over old ones.
            comparison_pages = {**existing, **{page.page_id: page for page in kept}}
            for finding in checker(
                units, list(comparison_pages.values()), ledger, llm, config, finalize=False,
                on_capped=conflict_limit_reached,
            ):
                if finding.failure is not None:
                    errors += 1
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
            from sb.search import SearchIndex

            explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
            SearchIndex(vault_root=vault.root, registry_path=explicit).project()
        held = any(
            row.attempts >= config.caps["max_derivation_attempts"]
            for stage_name in ("compile", "conflict")
            for status in (DerivStatus.FAILED.value, DerivStatus.PENDING.value)
            for row in ledger.list_derivations(status=status, stage=stage_name)
        )
        return StageReport(
            tuple(page for page in kept if page.page_id not in committed_ids),
            sum(1 for page in kept if page.page_id.startswith("conflicts/")),
            errors,
            max(len(kept) + errors, int(bool(run_id))),
            capped,
            written=len(committed_pages),
            derivations=tuple(derivations),
            compiled_by=(config.llm.prompt_version, config.llm.model_id),
            failure="DERIVATIONS_HELD" if held else None,
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
        if (existing is not None and existing.status in {
            DerivStatus.FAILED.value, DerivStatus.SUPERSEDED.value,
        } and not _reopen_failed(ledger, key, config.caps["max_derivation_attempts"])):
            return StageReport((), 0, 1, 1, False, failure="DERIVATIONS_HELD")
        if existing is not None and existing.status == DerivStatus.PENDING.value and existing.attempts >= config.caps["max_derivation_attempts"]:
            return StageReport((), 0, 1, 1, False, failure="DERIVATIONS_HELD")
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


def _publish_life_events(config: Config, ledger: Ledger, vault: Vault, run_id: str,
                         events: Sequence[object]) -> int:
    """Publish workflow changes through the existing writer and record identity boundary."""
    from sb.life_views import page_for_event, source_uri
    from sb.memory_records import parse_page_records
    from sb.store.life_journal import LifeJournal

    compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
    journal = LifeJournal(ledger.life_store())
    count = 0
    for event in events:
        source = SourceItem(event.source_id, source_uri(event), event.source_version,
                            event.raw_digest, run_id, run_id)
        ledger.upsert_source_item(source)
        ledger.bind_source_access(source, config.source_access[event.source_id])
        page = page_for_event(event)
        access = ledger.compiled_page_access(tuple((cite.origin, cite.hash) for cite in page.sources))
        report = StageReport((page,), 0, 0, 1, False,
                             compiled_by=("life-v1", "deterministic-v1"))
        committed, _, _ = _commit_pages(config=config, root=vault.root, vault=vault,
            run_id=run_id, report=report, line=f"{run_id} life {page.page_id}",
            compiled=compiled, ledger=ledger, project=False)
        raw = subprocess.check_output(["git", "-C", str(vault.root), "show",
                                       f"{committed or 'HEAD'}:{git_rel(page.page_id)}"])
        ledger.bind_page_access(git_rel(page.page_id).removesuffix(".md"),
                               "sha256:" + hashlib.sha256(raw).hexdigest(), access)
        journal.bind_records(event, parse_page_records(raw, page.page_id))
        count += 1
    if count and ".staging" not in vault.root.parts:
        from sb.search import SearchIndex
        explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
        SearchIndex(vault_root=vault.root, registry_path=explicit).project()
    return count


def run_life_workflow(config: Config, command: str, data: dict[str, object], *,
                      source_ids: tuple[str, ...], scopes: tuple[str, ...],
                      now: datetime | None = None, client: bool = False,
                      device_id: str = "owner", client_can_write: bool | None = None) -> tuple[RunOutcome, dict[str, object]]:
    """Commit one workflow operation; never send a network request inside the stage."""
    from sb.life_workflow import perform

    clock = now if now is not None else datetime.now(UTC)
    result: dict[str, object] = {}

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        store = ledger.life_store()
        with ledger.transaction():
            response, events = perform(config, store, command=command, data=data,
                source_ids=source_ids, scopes=scopes, now=clock, client=client, device_id=device_id,
                client_can_write=client_can_write)
        written = _publish_life_events(config, ledger, vault, run_id, events)
        result.update(response)
        return StageReport((), 0, 0, 1, False, written=written)

    outcome = _execute(config, stage, "compile")
    return outcome, result if outcome.exit_code == 0 and not outcome.already_running else {}


def run_life_import(config: Config, source_id: str, kind: str, raw: bytes, *,
                    filename: str = "export.json", now: datetime | None = None
                    ) -> tuple[RunOutcome, dict[str, object]]:
    """Explicit export/sensor ingress. Acknowledgement follows durable publication."""
    from uuid import NAMESPACE_URL, uuid5

    from sb.life_config import policy_for
    from sb.life_contracts import LifeInputError
    from sb.life_imports import prepare
    from sb.life_values import parse_event
    from sb.life_views import core_page_id
    from sb.store.life_journal import LifeJournal, identity

    clock = now if now is not None else datetime.now(UTC)
    prepared = prepare(config, source_id, kind, raw, filename=filename, now=clock)
    policy = policy_for(config, source_id, admission=False)
    result: dict[str, object] = {}

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        store = ledger.life_store()
        journal = LifeJournal(store)
        iid = identity("import_receipt", [source_id, kind, prepared.input_digest])
        previous = journal.raw("import_receipt", iid)
        original_digest = store.cas.put(raw)
        if original_digest != prepared.input_digest or not store.cas.exists(original_digest):
            raise LifeInputError("LIFE_RAW_UNAVAILABLE")
        original_source = SourceItem(source_id, "life-import/" + prepared.input_digest,
                                    prepared.input_digest, original_digest, run_id, run_id)
        ledger.upsert_source_item(original_source)
        ledger.bind_source_access(original_source, config.source_access[source_id])
        changed = {}
        receipts = []
        deleted_ids = []
        with ledger.transaction():
            for payload in prepared.payloads:
                event = parse_event(payload, policy, recorded_at=clock)
                if store.connection.execute("SELECT 1 FROM life_tombstones WHERE event_id=?",
                                            (event.event_id,)).fetchone():
                    continue
                current = store.connection.execute(
                    "SELECT current_revision,deleted FROM life_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
                expected = None if current is None else current[0]
                if current is not None:
                    prior_event = store.get(event.event_id, scopes=policy.scopes, now=clock)
                    known_version = store.connection.execute(
                        "SELECT 1 FROM life_event_revisions WHERE event_id=? AND source_version=?",
                        (event.event_id, event.source_version),
                    ).fetchone()
                    if (known_version is None and prior_event.evidence_level == "user_asserted"
                            and event.evidence_level != "user_asserted"):
                        raise LifeInputError("LIFE_SOURCE_USER_CORRECTION_CONFLICT")
                receipt = store.accept(payload, policy, key="import-" + event.raw_digest,
                                       expected_revision=expected, now=clock)
                receipts.append(receipt.as_dict())
                current_event = store.get(receipt.event_id, scopes=policy.scopes, now=clock)
                changed[current_event.event_id] = current_event
            for source_item in prepared.deleted_source_items:
                event_id = str(uuid5(NAMESPACE_URL, "sb-life:v1:" + source_id + "\0" + source_item))
                row = store.connection.execute("SELECT current_revision FROM life_events WHERE event_id=?",
                                               (event_id,)).fetchone()
                revision = row[0] if row else 1
                store.connection.execute("UPDATE life_events SET deleted=1 WHERE event_id=?", (event_id,))
                store.connection.execute(
                    "INSERT OR IGNORE INTO life_tombstones(event_id,revision,scopes_json,deleted_at) VALUES(?,?,?,?)",
                    (event_id, revision, json.dumps(policy.scopes), clock.isoformat()),
                )
                deleted_ids.append(event_id)
                changed.pop(event_id, None)
        written = _publish_life_events(config, ledger, vault, run_id, tuple(changed.values()))
        for event_id in deleted_ids:
            page_id = core_page_id(event_id)
            if (vault.root / git_rel(page_id)).exists():
                vault.forget_page(page_id, life_owned=True)
        if deleted_ids and ".staging" not in vault.root.parts:
            from sb.search import SearchIndex
            explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
            SearchIndex(vault_root=vault.root, registry_path=explicit).project()
        body = {"source_id": source_id, "kind": kind, "input_digest": prepared.input_digest,
                "receipts": receipts, "removed_event_ids": deleted_ids,
                "anchor": prepared.anchor, "state": "published",
                "device_projected": False, "physical_erasure": False}
        # Omit volatile receipt replay flags from the immutable import identity.
        for receipt in body["receipts"]:
            receipt.pop("replayed", None)
        if previous is not None:
            body = previous["body"]
        record = journal.put("import_receipt", iid, body, events=(), scopes=policy.scopes,
                             source_ids=(source_id,), now=clock)
        result.update(record["body"])
        result["import_receipt_id"] = iid
        if prepared.anchor is not None and previous is None:
            ledger.set_cursor("life-health:" + source_id + ":" + str(json.loads(raw).get("type")),
                              prepared.anchor, clock.isoformat())
        return StageReport((), 0, 0, len(receipts) + len(deleted_ids), False, written=written)

    outcome = _execute(config, stage, "compile")
    return outcome, result if not outcome.exit_code and not outcome.already_running else {}


def run_life_maintenance(config: Config, *, source_ids: tuple[str, ...],
                         scopes: tuple[str, ...], now: datetime | None = None,
                         limit: int = 1000) -> tuple[RunOutcome, dict[str, object]]:
    """Bounded lifecycle repair, even when new capture is OFF.

    Only selected source-owned pages are repaired or withdrawn. This does not
    erase shared original bytes or run arbitrary recovery/deployment commands.
    """
    from sb.life_config import policies
    from sb.life_contracts import LifeInputError
    from sb.life_values import instant
    from sb.life_views import core_page_id
    from sb.store.life import _decode

    configured = policies(config)
    if (type(limit) is not int or not 1 <= limit <= 1000 or not source_ids
            or any(s not in configured for s in source_ids)
            or not {v for s in source_ids for v in configured[s].scopes}.issubset(scopes)):
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    clock = now if now is not None else datetime.now(UTC)
    result: dict[str, object] = {}

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        store = ledger.life_store()
        placeholders = ",".join("?" for _ in source_ids)
        rows = store.connection.execute(
            "SELECT e.event_id,e.current_revision,e.deleted,e.expires_at,r.body_json,r.body_digest "
            "FROM life_events e JOIN life_event_revisions r ON r.event_id=e.event_id "
            "AND r.revision=e.current_revision WHERE e.source_id IN (" + placeholders + ") "
            "ORDER BY e.event_id", source_ids,
        )
        repaired = removed = expired = 0
        work = []
        for row in rows:
            event = _decode((row[4], row[5]))
            if not set(event.scopes).issubset(scopes):
                continue
            policy = configured[event.source_id]
            live = (not row[2] and instant(row[3]) > clock and policy.enabled
                    and policy.scopes == event.scopes and policy.sensitivity == event.sensitivity
                    and policy.policy_revision == event.policy_revision
                    and policy.external_processing == event.external_processing
                    and not store.cas.is_tombstoned(event.raw_digest)
                    and store.cas.exists(event.raw_digest))
            page_id = core_page_id(event.event_id)
            path = vault.root / git_rel(page_id)
            must_expire = not row[2] and instant(row[3]) <= clock
            if live:
                from sb.life_visibility import allowed
                try:
                    raw = subprocess.check_output(["git", "-C", str(vault.root), "show", "HEAD:" + git_rel(page_id)], stderr=subprocess.DEVNULL)
                except subprocess.CalledProcessError:
                    raw = None
                if raw is not None and allowed(vault.root, page_id, raw=raw, config=config, now=clock):
                    continue
            elif not path.exists() and not must_expire:
                continue
            work.append((event, live, must_expire))
            if len(work) > limit:
                break
        more = len(work) > limit
        for event, live, must_expire in work[:limit]:
            if must_expire:
                with ledger.transaction():
                    store.connection.execute("UPDATE life_events SET deleted=1 WHERE event_id=?", (event.event_id,))
                    store.connection.execute(
                        "INSERT OR IGNORE INTO life_tombstones(event_id,revision,scopes_json,deleted_at) VALUES(?,?,?,?)",
                        (event.event_id, event.revision, json.dumps(event.scopes), clock.isoformat()),
                    )
                expired += 1
            if live:
                repaired += _publish_life_events(config, ledger, vault, run_id, (event,))
            else:
                page_id = core_page_id(event.event_id)
                if (vault.root / git_rel(page_id)).exists():
                    vault.forget_page(page_id, life_owned=True)
                    removed += 1
        if removed and ".staging" not in vault.root.parts:
            from sb.search import SearchIndex
            explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
            SearchIndex(vault.root, registry_path=explicit).project()
        result.update(repaired=repaired, withdrawn_pages=removed, expired_events=expired,
                      more_pending=more, shared_raw_physically_erased=False)
        return StageReport((), 0, 0, min(len(work), limit), more, written=repaired + removed)

    outcome = _execute(config, stage, "compile")
    return outcome, result if not outcome.exit_code and not outcome.already_running else {}


def run_life_batch(
    config: Config, source_id: str, items: Sequence[Mapping[str, object]], *,
    now: datetime | None = None,
) -> tuple[RunOutcome, tuple[dict[str, object], ...]]:
    """Explicit SB2 capture/compile through the existing writer and generation boundary.

    The HTTP layer may acknowledge only a successful returned outcome. Receipts
    remain accepted, not 'read by the user'; View ACK and delivery are separate.
    """
    from sb.life_config import policy_for, settings
    from sb.life_contracts import LifeInputError
    from sb.life_values import canonical_bytes, parse_event, text
    from sb.life_views import page_for_event, source_uri

    policy = policy_for(config, source_id)
    clock = now if now is not None else datetime.now(UTC)
    if not 1 <= len(items) <= 100 or len(canonical_bytes(items)) > 24 * 1024 * 1024:
        raise LifeInputError("LIFE_BATCH_INVALID")
    prepared: list[tuple[str, Mapping[str, object], int | None]] = []
    for item in items:
        if not isinstance(item, Mapping) or set(item) - {"idempotency_key", "payload", "expected_revision"}:
            raise LifeInputError("LIFE_BATCH_INVALID")
        payload = item.get("payload")
        if not isinstance(payload, dict):
            raise LifeInputError("LIFE_BATCH_INVALID")
        key = text(item.get("idempotency_key"), maximum=256)
        expected = item.get("expected_revision")
        if expected is not None and (type(expected) is not int or expected < 0):
            raise LifeInputError("LIFE_REVISION_INVALID")
        event = parse_event(payload, policy, recorded_at=clock)
        if event.event_type.startswith("location_"):
            settings(config).require("location_capture")
        if event.event_type.startswith("health_"):
            settings(config).require("health_capture")
        prepared.append((key, payload, expected))
    receipts: list[dict[str, object]] = []

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        store = ledger.life_store()
        pages: dict[str, PageSpec] = {}
        with ledger.transaction():
            for key, payload, expected in prepared:
                receipt = store.accept(payload, policy, key=key, now=clock, expected_revision=expected)
                receipts.append(receipt.as_dict())
                event = store.get(receipt.event_id, scopes=policy.scopes, now=clock)
                source = SourceItem(event.source_id, source_uri(event), event.source_version,
                                    event.raw_digest, run_id, run_id)
                ledger.upsert_source_item(source)
                ledger.bind_source_access(source, config.source_access[source_id])
                page = page_for_event(event)
                pages[page.page_id] = page
        compiled = _Compiled(vault.root, ContentAddressedStore(vault.root))
        for page in pages.values():
            access = ledger.compiled_page_access(tuple((cite.origin, cite.hash) for cite in page.sources))
            report = StageReport((page,), 0, 0, 1, False,
                                 compiled_by=("life-v1", "deterministic-v1"))
            committed, _, _ = _commit_pages(
                vault.root, vault, run_id, report, f"{run_id} life {page.page_id}",
                compiled, ledger=ledger, project=False, config=config,
            )
            raw = subprocess.check_output(["git", "-C", str(vault.root), "show",
                                           f"{committed or 'HEAD'}:{git_rel(page.page_id)}"])
            ledger.bind_page_access(git_rel(page.page_id).removesuffix(".md"),
                                   "sha256:" + hashlib.sha256(raw).hexdigest(), access)
            from sb.memory_records import parse_page_records
            from sb.store.life_journal import LifeJournal
            page_event = next(store.get(receipt["event_id"], scopes=policy.scopes, now=clock)
                              for receipt in receipts
                              if page.page_id == "wiki/life-event-" + receipt["event_id"])
            LifeJournal(store).bind_records(page_event, parse_page_records(raw, page.page_id))
        if pages and ".staging" not in vault.root.parts:
            from sb.search import SearchIndex
            explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
            SearchIndex(vault_root=vault.root, registry_path=explicit).project()
        return StageReport((), 0, 0, len(prepared), False, written=len(pages))

    outcome = _execute(config, stage, "compile")
    if outcome.exit_code != 0 or outcome.already_running:
        return outcome, ()
    return outcome, tuple(receipts)


def run_life_forget(
    config: Config, source_id: str, event_id: str, expected_revision: int, *,
    now: datetime | None = None,
) -> RunOutcome:
    """Withdraw one event and its current core page; retained raw/history is explicit.

    This is not physical erasure of shared CAS or external/offline copies.
    Withdrawal remains available when creation flags or the source are OFF.
    """
    from sb.life_config import policy_for
    from sb.life_contracts import LifeInputError
    from sb.life_views import core_page_id

    policy = policy_for(config, source_id, admission=False)
    clock = now if now is not None else datetime.now(UTC)

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del run_id
        store = ledger.life_store()
        prior = next((t for t in store.tombstones(scopes=policy.scopes)
                      if t["event_id"] == event_id), None)
        if prior is None:
            event = store.get(event_id, scopes=policy.scopes, now=clock)
            if event.source_id != source_id:
                raise LifeInputError("LIFE_EVENT_NOT_FOUND")
            store.forget(event_id, scopes=policy.scopes,
                         expected_revision=expected_revision, now=clock)
        elif prior["revision"] != expected_revision:
            raise LifeInputError("LIFE_REVISION_CONFLICT")
        page_id = core_page_id(event_id)
        if (vault.root / git_rel(page_id)).exists():
            vault.forget_page(page_id, life_owned=True)
        if ".staging" not in vault.root.parts:
            from sb.search import SearchIndex
            explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
            SearchIndex(vault_root=vault.root, registry_path=explicit).project()
        return StageReport((), 0, 0, 1, False, written=1)

    return _execute(config, stage, "effect")


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


def _record_batch_progress(root: Path, batch_id: str, started: str,
                           outcomes: Sequence[tuple[str, RunOutcome]]) -> None:
    with Ledger(root) as ledger:
        ledger.record_stage(RunStage(batch_id, "batch", started, None, "running",
            len(outcomes), sum(value.written for _, value in outcomes),
            sum(value.errors for _, value in outcomes), json.dumps({
                "stages": [{"stage": stage, "run_id": value.run_id, "status": value.status}
                           for stage, value in outcomes],
            }, separators=(",", ":"))))


def _run_all_mutable(config: Config, sources: Sequence[str] | None = None) -> RunOutcome:
    root = Path(config.vault_root)
    fd = _try_lock(root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    batch_id, started = uuid4().hex, datetime.now(UTC).isoformat()
    outcomes: list[tuple[str, RunOutcome]] = []
    try:
        with Ledger(root) as ledger:
            ledger.interrupt_stale_batches(started)
            ledger.record_stage(RunStage(batch_id, "batch", started, None, "running", 0, 0, 0))
        try:
            ingest = _run_locked(root, _ingest(config, sources, None), "ingest", config)
            outcomes.append(("ingest", ingest))
            _record_batch_progress(root, batch_id, started, outcomes)
            compiled = _run_locked(root, _compile_stage(config, "cli"), "compile", config)
            outcomes.append(("compile", compiled))
            _record_batch_progress(root, batch_id, started, outcomes)
            if ingest.written == 0 and compiled.pages == 0:
                brief = compiled if compiled.exit_code == 0 else ingest
                if ingest.status == "capped" and ingest.exit_code == 0:
                    brief = ingest
            else:
                brief = _run_locked(root, _brief_stage(config, None, "cli"), "brief", config)
                outcomes.append(("brief", brief))
                _record_batch_progress(root, batch_id, started, outcomes)
            chosen = _choose_batch_outcome(ingest, compiled, brief)
        except Exception:
            with Ledger(root) as ledger:
                ledger.record_stage(RunStage(batch_id, "batch", started,
                    datetime.now(UTC).isoformat(), "failed", len(outcomes),
                    sum(value.written for _, value in outcomes),
                    sum(value.errors for _, value in outcomes) + 1,
                    json.dumps({"failure": "batch interrupted by an exception",
                                "stages": [{"stage": stage, "run_id": value.run_id,
                                            "status": value.status}
                                           for stage, value in outcomes]}, separators=(",", ":"))))
            raise
        with Ledger(root) as ledger:
            ledger.record_stage(RunStage(batch_id, "batch", started,
                datetime.now(UTC).isoformat(), chosen.status, len(outcomes),
                sum(value.written for _, value in outcomes),
                sum(value.errors for _, value in outcomes), json.dumps({
                    "selected_run_id": chosen.run_id,
                    "stages": [{"stage": stage, "run_id": value.run_id,
                                "status": value.status} for stage, value in outcomes],
                }, separators=(",", ":"))))
        return chosen
    finally:
        _unlock(fd)


def _choose_batch_outcome(ingest: RunOutcome, compiled: RunOutcome, brief: RunOutcome) -> RunOutcome:
    chosen = brief
    for outcome in (ingest, compiled, brief):
        if outcome.exit_code != 0:
            return outcome
        if outcome.status == "capped":
            chosen = outcome
    # A later successful stage does not resolve errors from an earlier one.
    # Preserve the failing stage's run ID and error count for callers.
    for outcome in (ingest, compiled, brief):
        if outcome.status == "partial":
            return outcome
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
            # A SourceCite sid may bind origin+hash rather than hash[:8]. Use
            # the actual declared citation identities; never rewrite records
            # merely to satisfy an obsolete shortcut in the audit.
            spec = read_page_spec(root, path.relative_to(root).as_posix().removesuffix(".md"), rendered_text=text)
            if spec is not None:
                known = {cite.sid for cite in spec.sources}
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
