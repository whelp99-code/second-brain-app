"""Thin run orchestration: lock, ledger, logs, briefing I/O, vault writes.
# noqa: SIZE_OK -- legacy stage assembly; public writers now enter generation_runtime
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from uuid import uuid4

from sb.config import Config
from sb.connectors.base import SourceAdapter
from sb.contracts import Blob, BriefingInputs, PageSpec, Unit
from sb.erasure import ErasureError, ReingressGate
from sb.generation_runtime import (
    GenerationAuthority,
    GenerationMutation,
    GenerationMutationService,
    GenerationOperation,
)
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
from sb.vault import GitCommandError, Vault, VaultLintError

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


class StageFn(Protocol):
    def __call__(self, ledger: Ledger, vault: Vault, run_id: str) -> StageReport: ...


class BriefGenerator(Protocol):
    def __call__(self, inputs: BriefingInputs, llm: LLMClient | None, config: Config) -> PageSpec: ...


class _CitedFake:
    def generate(self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120) -> str:
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
        if any(row.content_hash != digest for row in items if row.source_id == source_id and row.source_uri == uri):
            return True
    return False


def _cite_line(source_id: str, source_uri: str, digest: str, text: str) -> str:
    return f"origin={source_id}:{source_uri} hash={digest} [^{digest[:8]}] text={text}"


def _blob_line(cas: ContentAddressedStore, digest: str, fallback: str) -> str:
    if not cas.exists(digest):
        return fallback
    lines = cas.get(digest).decode("utf-8", errors="replace").splitlines()
    return lines[0].strip() if lines and lines[0].strip() else fallback


def collect_briefing_inputs(ledger: Ledger, vault_root: Path, *, today: date | None = None) -> BriefingInputs:
    """Load K4 briefing inputs from the ledger and tracked vault files."""
    day, root = (datetime.now().astimezone().date() if today is None else today), Path(vault_root)
    yesterday, cas = day - timedelta(days=1), ContentAddressedStore(root)
    y_items = [
        _cite_line(item.source_id, item.source_uri, item.content_hash, _blob_line(cas, item.content_hash, item.source_uri))
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
                upcoming.append(_cite_line(item.source_id, item.source_uri, item.content_hash, raw.strip()))
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
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    return lines[-1] if lines else None


def _select_adapters(
    chosen: Mapping[str, SourceAdapter], source_ids: Sequence[str] | None, config: Config
) -> list[SourceAdapter]:
    del config
    if source_ids is None:
        return list(chosen.values())
    names = set(source_ids)
    return [
        adapter
        for adapter_id, adapter in chosen.items()
        if adapter_id in names or adapter.source_id in names
    ]


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


def _source_content_ids(ledger: Ledger, root: Path) -> tuple[str, ...]:
    cas = ContentAddressedStore(root)
    return tuple(sorted({item.content_hash for item in ledger.list_source_items() if cas.exists(item.content_hash)}))


def _brief_facts(inputs: BriefingInputs, day: date, content_ids: tuple[str, ...]) -> str:
    payload = "\0".join((
        day.isoformat(),
        *content_ids, "\x1e", *inputs.open_conflict_pages, "\x1e",
        *inputs.stale_pages, "\x1e", *inputs.upcoming_items, "\x1e",
        inputs.last_brief or "",
    ))
    return hashlib.sha256(payload.encode()).hexdigest()


def _commit_pages(root: Path, vault: Vault, run_id: str, report: StageReport, line: str, compiled: _Compiled) -> tuple[str | None, int, int]:
    del root
    result = vault.write_pages(report.pages, run_id, compiled, log_line=line)
    compiled.remember(report.pages)
    return result.commit, result.pages, result.conflicts


def _finish_deriv(ledger: Ledger, key: str | None, digest: str, path: str) -> None:
    if key is None:
        return
    ledger.mark_done(key, DerivationOutput(digest, path))


def _fail_deriv(ledger: Ledger, key: str | None, error: str) -> None:
    if key is None:
        return
    ledger.mark_failed(key, error)


def _reopen_failed(ledger: Ledger, key: str) -> None:
    """Return a failed brief key to pending so the same key can mark_running again."""
    row = ledger.get_derivation(key)
    if row is None or row.status != DerivStatus.FAILED.value:
        return
    path = ledger.db_path
    ledger.close()
    with sqlite3.connect(path) as conn:
        _ = conn.execute(
            "UPDATE derivation SET status=?, error=NULL, finished_at=NULL WHERE deriv_key=?",
            (DerivStatus.PENDING.value, key),
        )
        conn.commit()
    ledger.open()


def _run_locked(root: Path, stage: StageFn) -> RunOutcome:
    run_id, started, vault = uuid4().hex, datetime.now().astimezone().isoformat(), Vault(root=root)
    compiled = _Compiled(root, ContentAddressedStore(root))
    with Ledger(root) as ledger:
        _ = ledger.reset_stale_running(run_id)
        report = stage(ledger, vault, run_id)
        if report.capped:
            status, exit_code = "capped", 0
        elif report.attempted > 0 and report.errors * 2 > report.attempted:
            status, exit_code = "failed", 1
        else:
            status, exit_code = "ok", 0
        commit, pages, conflicts, errors = None, 0, report.conflicts, report.errors
        rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={{2}}"
        if report.pages:
            try:
                commit, pages, conflicts = _commit_pages(
                    root, vault, run_id, report, rendered.format(len(report.pages), conflicts, errors), compiled
                )
                _finish_deriv(ledger, report.deriv_key, hashlib.sha256(report.pages[0].body_md.encode()).hexdigest(), f"{report.pages[0].page_id}.md")
            except (VaultLintError, GitCommandError, OSError) as exc:
                _fail_deriv(ledger, report.deriv_key, str(exc))
                status, exit_code, errors = "failed", 1, max(errors, 1)
        if status == "failed":
            rendered = f"{started} run {run_id} {status} pages={{0}} conflicts={{1}} errors={{2}}"
        ledger.record_run(Run(run_id, started, datetime.now(UTC).isoformat(), commit, status))
        log = root / ".sb" / "runs.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            _ = handle.write(rendered.format(pages, conflicts, errors) + "\n")
        return RunOutcome(run_id, status, pages, conflicts, errors, exit_code, commit, False, report.written)


def _execute(config: Config, stage: StageFn, operation: GenerationOperation) -> RunOutcome:
    root = Path(config.vault_root)
    lock_root = Path(config.state_root) if root.is_symlink() else root
    fd = _try_lock(lock_root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    service = GenerationMutationService.from_config(config)
    try:
        result = service.mutate(
            GenerationMutation(
                mutation_id=f"pipeline:{operation.value}:{uuid4().hex}",
                operation=operation,
                now=datetime.now(UTC),
                authority=GenerationAuthority(None, None),
                apply=lambda staging: _run_locked(staging, stage),
            )
        )
        git_commit = result.generation.head if result.value.git_commit is not None else None
        return replace(result.value, git_commit=git_commit)
    finally:
        service.close()
        _unlock(fd)


def _ingest(config: Config, source_ids: Sequence[str] | None, limit: int | None) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        from sb.connectors import discover_adapters

        chosen = discover_adapters(config)
        adapters = _select_adapters(chosen, source_ids, config)
        cas, cap = ContentAddressedStore(vault.root), config.caps["max_new_units_per_run"] if limit is None else limit
        reingress = ReingressGate(Path(config.state_root) / "reingress.db")
        seen = {(item.source_id, item.source_uri, item.source_version) for item in ledger.list_source_items()}
        errors = attempted = written = 0
        capped = False
        for adapter in adapters:
            try:
                items = adapter.scan(ledger.get_cursor(adapter.source_id))
            except (OSError, RuntimeError):
                errors += 1
                attempted += 1
                continue
            progressed = False
            blocked = False
            for ref, data, meta in items:
                version_key = (ref.source_id, ref.source_uri, ref.source_version)
                if version_key in seen:
                    continue
                if attempted >= cap:
                    capped = True
                    break
                attempted += 1
                if meta.get("skip_reason"):
                    skip_digest = hashlib.sha256(f"skip:{ref.source_version}".encode()).hexdigest()
                    ledger.upsert_source_item(SourceItem(
                        ref.source_id, ref.source_uri, ref.source_version, skip_digest, run_id, run_id
                    ))
                    seen.add(version_key)
                    progressed = True
                    continue
                digest = hashlib.sha256(data).hexdigest()
                source_identity = (
                    ref.source_id
                    if len(ref.source_id) == 64
                    and all(character in "0123456789abcdef" for character in ref.source_id)
                    else hashlib.sha256(
                        f"{ref.source_id}\0{ref.source_uri}".encode()
                    ).hexdigest()
                )
                try:
                    reingress.check(
                        source_identity=source_identity,
                        content_identity=digest,
                    )
                    reingress.check_content(data)
                except ErasureError:
                    blocked = True
                    continue
                units = _materialize(data, digest, ref.source_uri, f"{ref.source_id}:{ref.source_uri}")
                if not units and data:
                    ledger.upsert_source_item(SourceItem(
                        ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id
                    ))
                    seen.add(version_key)
                    progressed = True
                    continue
                try:
                    _ = cas.put(data)
                    ledger.upsert_source_item(SourceItem(
                        ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id
                    ))
                    _store_units(ledger, units)
                    seen.add(version_key)
                    progressed = True
                    written += 1
                except OSError:
                    errors += 1
                    ledger.upsert_source_item(SourceItem(
                        ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id
                    ))
                    seen.add(version_key)
                    progressed = True
            if capped:
                break
            if not blocked and (progressed or not attempted):
                ledger.set_cursor(adapter.source_id, adapter.next_cursor(), datetime.now(UTC).isoformat())
        reingress.close()
        return StageReport((), 0, errors, attempted, capped, None, written)

    return stage


def _llm(config: Config, llm_mode: str) -> LLMClient:
    from sb.llm import CliLLM

    return _CitedFake() if llm_mode == "fake" else CliLLM(list(config.llm.argv_template))


def _page_ready(root: Path, page: PageSpec) -> bool:
    known = {cite.sid for cite in page.sources}
    for match in re.finditer(r"\[\^([^\]]+)\]", page.body_md):
        if match.group(1) not in known:
            return False
    return all(len(cite.hash) == 64 and (root / "raw" / cite.hash[:2] / cite.hash).is_file() for cite in page.sources)


def _compile_stage(config: Config, llm_mode: str) -> StageFn:
    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        try:
            from sb.compile import compile_pages
        except ModuleNotFoundError:
            return StageReport((), 0, 0, 0, False)
        units = _load_units(ledger, vault.root)
        llm = _llm(config, llm_mode)
        pages = list(compile_pages(units, ledger, llm, config))
        capped = bool(pages) and pages[-1].status == "CAPPED"
        kept = list(pages[:-1] if capped else pages)
        errors = 0
        checker = None
        try:
            from sb.conflict import check as checker
        except ModuleNotFoundError:
            checker = None
        if checker is not None:
            for finding in checker(units, kept, ledger, llm, config):
                page = finding.page
                if page is None:
                    continue
                if _page_ready(vault.root, page):
                    kept.append(page)
        return StageReport(tuple(kept), sum(1 for page in kept if page.page_id.startswith("conflicts/")), errors, max(len(kept), int(bool(run_id))), capped)

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
        return StageReport((page,), 0, 0, 1, False, key)

    return stage


def run_ingest(
    config: Config, sources: Sequence[str] | None, *, stage: StageFn | None = None, limit: int | None = None
) -> RunOutcome:
    return _execute(
        config,
        stage if stage is not None else _ingest(config, sources, limit),
        GenerationOperation.INGEST,
    )


def run_compile(config: Config, *, compiler: StageFn | None = None, llm_mode: str = "cli") -> RunOutcome:
    return _execute(
        config,
        compiler if compiler is not None else _compile_stage(config, llm_mode),
        GenerationOperation.COMPILE,
    )


def run_brief(config: Config, *, generator: BriefGenerator | None = None, llm_mode: str = "cli") -> RunOutcome:
    return _execute(
        config,
        _brief_stage(config, generator, llm_mode),
        GenerationOperation.BRIEF,
    )


def run_all(config: Config, sources: Sequence[str] | None = None) -> RunOutcome:
    def stages(root: Path) -> RunOutcome:
        ingest = _run_locked(root, _ingest(config, sources, None))
        compiled = _run_locked(root, _compile_stage(config, "cli"))
        if ingest.written == 0 and compiled.pages == 0:
            brief = compiled if compiled.exit_code == 0 else ingest
            if ingest.status == "capped" and ingest.exit_code == 0:
                brief = ingest
        else:
            brief = _run_locked(root, _brief_stage(config, None, "cli"))
        chosen = brief
        for outcome in (ingest, compiled, brief):
            if outcome.exit_code != 0:
                return outcome
            if outcome.status == "capped":
                chosen = outcome
        return chosen

    root = Path(config.vault_root)
    lock_root = Path(config.state_root) if root.is_symlink() else root
    fd = _try_lock(lock_root)
    if fd is None:
        return RunOutcome("", "ok", 0, 0, 0, 0, None, True)
    service = GenerationMutationService.from_config(config)
    try:
        result = service.mutate(
            GenerationMutation(
                mutation_id=f"pipeline:run:{uuid4().hex}",
                operation=GenerationOperation.RUN,
                now=datetime.now(UTC),
                authority=GenerationAuthority(None, None),
                apply=stages,
            )
        )
        git_commit = result.generation.head if result.value.git_commit is not None else None
        return replace(result.value, git_commit=git_commit)
    finally:
        service.close()
        _unlock(fd)


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
