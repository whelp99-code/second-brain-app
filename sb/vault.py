"""Vault containment helpers.
# noqa: SIZE_OK -- one vault containment boundary
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Final, Protocol, cast, override

import yaml

from sb.contracts import PageSpec, SourceCite
from sb.store import parse_compiled_by

BOT_NAME: Final = "second-brain-bot"
BOT_EMAIL: Final = "sb@local"
GITIGNORE_BODY: Final = "raw/\n.sb/\n"
INIT_MESSAGE: Final = "sb: init vault"
FOOTNOTE_RE: Final = re.compile(r"\[\^([^\]]+)\]")
# Models annotate the source span either as "origin span=0-12" or "origin, span=0-12".
SPAN_SUFFIX_RE: Final = r",? span=[0-9]+-[0-9]+"
VAULT_DIRS: Final = ("wiki", "daily", "conflicts", "inbox", "raw", ".sb", "wiki/_proposed")


class CompiledHashLedger(Protocol):
    def last_compiled_hash(self, page_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class VaultLintError(Exception):
    reasons: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return "; ".join(self.reasons)


@dataclass(frozen=True, slots=True)
class RunCommitNotFoundError(Exception):
    run_id: str

    @override
    def __str__(self) -> str:
        return f"no vault commit for run {self.run_id}"


@dataclass(frozen=True, slots=True)
class GenerationAuthorityRequiredError(Exception):
    @override
    def __str__(self) -> str:
        return "ROLLBACK_REQUIRES_GENERATION_AUTHORITY"


@dataclass(frozen=True, slots=True)
class GitCommandError(Exception):
    argv: tuple[str, ...]
    stderr: str

    @override
    def __str__(self) -> str:
        return f"git {' '.join(self.argv)} failed: {self.stderr}"


@dataclass(frozen=True, slots=True)
class PathEscapeError(Exception):
    page_id: str

    @override
    def __str__(self) -> str:
        return f"page_id escapes vault: {self.page_id}"


@dataclass(frozen=True, slots=True)
class WriteResult:
    pages: int
    conflicts: int
    proposals: int
    commit: str | None
    applied_page_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Vault:
    root: Path

    def rebind_erased_sources(
        self, effect_id: str, erased_hashes: frozenset[str], store_snapshot: Callable[[bytes], str],
    ) -> None:
        """Bind surviving statements to an effect snapshot when their raw source was erased.

        The effect receipt is the new provenance; a removed source is never
        represented as still available. Pages without affected citations stay byte-identical.
        """
        for folder in ("wiki", "daily", "conflicts"):
            for path in (self.root / folder).rglob("*.md"):
                split = _split_rendered(path.read_bytes().decode("utf-8"))
                if split is None:
                    continue
                block, body = split
                loaded = cast(object, yaml.safe_load(block))
                if not isinstance(loaded, dict):
                    continue
                fields = cast(dict[str, object], loaded)
                sources = fields.get("sources")
                if not isinstance(sources, list):
                    continue
                entries = [cast(dict[str, object], item) for item in cast(list[object], sources)
                           if isinstance(item, dict)]
                missing = [item for item in entries if isinstance(item.get("hash"), str)
                           and item["hash"] in erased_hashes]
                if not missing:
                    continue
                sids = {str(item["sid"]) for item in missing if "sid" in item}
                lines: list[str] = []
                for line in body.splitlines(keepends=True):
                    if any(line.strip().startswith(f"[^{sid}]:") for sid in sids):
                        continue
                    plain = line
                    for sid in sids:
                        plain = plain.replace(f"[^{sid}]", "")
                    # A deleted statement's orphan marker is not a surviving fact.
                    lines.append(line if plain.strip() or not line.strip() else "")
                body = "".join(lines).strip()
                snapshot = body
                for sid in sids:
                    snapshot = snapshot.replace(f"[^{sid}]", "")
                retained = [item for item in entries if item not in missing]
                if any(f"[^{sid}]" in body for sid in sids):
                    content_hash = store_snapshot(snapshot.encode("utf-8"))
                    marker = content_hash[:8]
                    for sid in sids:
                        body = body.replace(f"[^{sid}]", f"[^{marker}]")
                    origin = f"memory-effect:{effect_id}"
                    retained.append({"sid": marker, "origin": origin, "hash": content_hash})
                    body += f"\n\n[^{marker}]: {origin}"
                fields["sources"] = retained
                dumped = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)
                _atomic_write(path, f"---\n{dumped}---\n\n{body}\n")

    def write_staged_page(self, page: PageSpec, *, compiled_by: str, updated: str) -> None:
        """Write a validated immutable request page before generation sealing.

        The generation mutation owns the staging directory and its later commit.
        Existing different bytes are never overwritten by this insertion surface.
        """
        reasons = _lint(self.root, page)
        if reasons:
            raise VaultLintError(tuple(reasons))
        destination = _safe_rel(self.root, _rel_for(page.page_id))
        rendered = _render(page, compiled_by=compiled_by, updated=updated)
        if destination.exists():
            if destination.read_text(encoding="utf-8") != rendered:
                raise VaultLintError((f"{page.page_id}: staged page identity collision",))
            return
        _atomic_write(destination, rendered)
        destination.chmod(0o600)

    def write_pages(
        self,
        pages: Sequence[PageSpec],
        run_id: str,
        ledger: CompiledHashLedger,
        *,
        log_line: str | None = None,
        compiled_by: tuple[str, str] | None = None,
    ) -> WriteResult:
        reasons = tuple(reason for page in pages for reason in _lint(self.root, page))
        if reasons:
            raise VaultLintError(reasons=reasons)
        planned = [(_safe_rel(self.root, _rel_for(page.page_id)), page) for page in pages]
        try:
            version = metadata.version("second-brain")
        except metadata.PackageNotFoundError:
            version = "1.0.0"
        prompt_version, model_id = compiled_by or ("v1", "unknown")
        counts, jobs = _plan_writes(
            self.root,
            planned,
            ledger,
            (
                f"sb/{version}|{prompt_version}|{model_id}",
                datetime.now(UTC).date().isoformat(),
            ),
        )
        n_pages, n_conflicts, n_proposals = counts
        if not jobs:
            return WriteResult(n_pages, n_conflicts, n_proposals, None)
        log_path = self.root / "log.md"
        log_prev = log_path.read_bytes() if log_path.is_file() else None
        snapshots = tuple(
            (dest, dest.read_bytes() if dest.is_file() else None) for dest, *_ in jobs
        )
        written: list[Path] = []
        try:
            for dest, text, kind, page_id in jobs:
                _atomic_write(dest, text)
                written.append(dest)
                if kind != "proposal":
                    _write_compiled_marker(self.root, page_id, dest)
                if kind == "proposal":
                    slug = page_id.replace("/", "-")
                    self.append_log(f"human-edit: {page_id} -> wiki/_proposed/{slug}.md")
                    written.append(log_path)
            if log_line is not None:
                self.append_log(log_line)
                written.append(log_path)
            message = f"sb: run {run_id} ({n_pages} pages, {n_conflicts} conflicts, {n_proposals} proposals)"
            commit = _commit_if_changed(self.root, message, written)
        except (GitCommandError, OSError):
            _restore(self.root, snapshots, log_path, log_prev)
            raise
        return WriteResult(n_pages, n_conflicts, n_proposals, commit,
                           tuple(page_id for _dest, _text, kind, page_id in jobs if kind != "proposal"))

    def append_log(self, line: str) -> None:
        path = self.root / "log.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        _atomic_write(path, f"{existing}{line.rstrip()}\n")

    def rollback(self, run_id: str) -> None:
        del run_id
        raise GenerationAuthorityRequiredError()

    def resolve_conflict(
        self,
        conflict_id: str,
        decision: str,
        note: str,
        run_id: str,
    ) -> str | None:
        """Record one explicit human conflict decision and commit it."""
        if decision not in {"keep-left", "keep-right", "note"}:
            raise ValueError("decision must be keep-left, keep-right, or note")
        clean_id = conflict_id.removeprefix("conflicts/").removesuffix(".md")
        path = _safe_rel(self.root, Path("conflicts") / f"{clean_id}.md")
        if not path.is_file():
            raise FileNotFoundError(path)
        split = _split_rendered(path.read_text(encoding="utf-8"))
        if split is None:
            raise VaultLintError((f"{clean_id}: invalid conflict page",))
        block, body = split
        loaded = cast(object, yaml.safe_load(block))
        if not isinstance(loaded, dict):
            raise VaultLintError((f"{clean_id}: invalid conflict frontmatter",))
        payload = cast(dict[str, object], loaded)
        resolved_at = datetime.now(UTC).isoformat()
        payload["status"] = "resolved"
        payload["resolution"] = {
            "decision": decision,
            "note": note.strip(),
            "resolved_at": resolved_at,
        }
        body = re.sub(
            r"(?m)(^## status\s*\n)open\s*$",
            r"\1resolved",
            body,
            count=1,
        )
        body = re.sub(r"(?ms)\n*## resolution\n.*\Z", "", body).rstrip()
        resolution = (
            "## resolution\n"
            f"- decision: {decision}\n"
            f"- resolved_at: {resolved_at}\n"
            f"- note: {note.strip() or 'none'}"
        )
        dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        _atomic_write(path, f"---\n{dumped}---\n\n{body}\n\n{resolution}\n")
        return _commit_if_changed(
            self.root,
            f"sb: resolve {run_id} {clean_id} ({decision})",
            [path],
        )

    def restore_life_pages(self, pages: Mapping[str, bytes]) -> str | None:
        """Exact current life bytes in an unpublished restore candidate.

        Called by life_restore only after archive validation and current-ledger
        capture. Identity, citation offsets and original record digests survive.
        Other wiki pages and every user MyNotes path are outside this boundary.
        """
        prefix = "wiki/life-event-"
        valid = re.compile(r"wiki/life-event-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.md\Z")
        if any(valid.fullmatch(path) is None or not isinstance(content, bytes)
               for path, content in pages.items()):
            raise VaultLintError(("LIFE_RESTORE_PAGE_INVALID",))
        current = tuple((self.root / "wiki").glob("life-event-*.md"))
        touched: list[Path] = []
        for path in current:
            relative = path.relative_to(self.root).as_posix()
            if valid.fullmatch(relative) is None or path.is_symlink():
                raise VaultLintError(("LIFE_RESTORE_PAGE_INVALID",))
            if relative not in pages:
                path.unlink()
                touched.append(path)
        for relative, content in pages.items():
            destination = _safe_rel(self.root, Path(relative))
            _atomic_write(destination, content.decode("utf-8"))
            touched.append(destination)
            _write_compiled_marker(self.root, relative.removesuffix(".md"), destination)
        del prefix
        return _commit_if_changed(self.root, "sb: preserve current life state on restore", touched)

    def forget_page(self, page_id: str, *, life_owned: bool = False) -> str | None:
        """Remove one compiled page through the existing git commit boundary."""
        if page_id.removesuffix(".md").startswith("wiki/life-event-") and not life_owned:
            raise VaultLintError(("LIFE_EVENT_API_REQUIRED",))
        rel = _rel_for(page_id)
        if rel.parts[0] not in {"wiki", "daily", "conflicts"} or len(rel.parts) != 2:
            raise PathEscapeError(page_id=page_id)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open(self.root, flags)
        try:
            folder_fd = os.open(rel.parts[0], flags, dir_fd=root_fd)
            try:
                file_fd = os.open(
                    rel.parts[1],
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=folder_fd,
                )
                try:
                    info = os.fstat(file_fd)
                    if not stat.S_ISREG(info.st_mode):
                        raise FileNotFoundError(self.root / rel)
                    os.unlink(rel.parts[1], dir_fd=folder_fd)
                finally:
                    os.close(file_fd)
            finally:
                os.close(folder_fd)
        finally:
            os.close(root_fd)
        return _commit_if_changed(self.root, f"sb: forget {page_id}", [self.root / rel])


def read_page_spec(root: Path | str, page_id: str, *, rendered_text: str | None = None) -> PageSpec | None:
    """Read one current rendered page as a PageSpec for persistent merge input."""
    root_path = Path(root)
    path = _safe_rel(root_path, _rel_for(page_id))
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8") if rendered_text is None else rendered_text
    split = _split_rendered(text)
    if split is None:
        return None
    block, body = split
    loaded = cast(object, yaml.load(block, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)))
    if not isinstance(loaded, dict):
        return None
    fields = cast(dict[str, object], loaded)
    stored_id = fields.get("id")
    title = fields.get("title")
    status = fields.get("status")
    raw_sources = fields.get("sources")
    if stored_id != page_id or not isinstance(title, str) or not isinstance(status, str):
        return None
    if not isinstance(raw_sources, list):
        return None
    sources: list[SourceCite] = []
    for raw in cast(list[object], raw_sources):
        if not isinstance(raw, dict):
            return None
        item = cast(dict[str, object], raw)
        sid, origin, digest = item.get("sid"), item.get("origin"), item.get("hash")
        if not isinstance(sid, str) or not isinstance(origin, str) or not isinstance(digest, str):
            return None
        raw_spans = item.get("spans", [])
        if not isinstance(raw_spans, list):
            return None
        raw_span_items = cast(list[object], raw_spans)
        spans = [span for span in raw_span_items if isinstance(span, str)]
        if len(spans) != len(raw_span_items):
            return None
        sources.append(SourceCite(sid, origin, digest, spans))
    compiled_by = fields.get("compiled_by")
    lineage = parse_compiled_by(compiled_by) if isinstance(compiled_by, str) else None
    derivation_key = fields.get("derivation_key")
    sensitivity = fields.get("sensitivity")
    if sensitivity is not None and (not isinstance(sensitivity, str) or sensitivity not in {"public", "personal", "sensitive", "restricted"}):
        return None
    return PageSpec(
        page_id,
        title,
        _strip_definitions(body, sources),
        sources,
        status,
        None if lineage is None else lineage[0],
        None if lineage is None else lineage[1],
        derivation_key if isinstance(derivation_key, str) else None,
        sensitivity if isinstance(sensitivity, str) else None,
    )


def _split_rendered(text: str) -> tuple[str, str] | None:
    if not text.startswith("---"):
        return None
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return None
    return rest[:end], rest[end + 4 :].lstrip("\n")


def _strip_definitions(body: str, sources: Sequence[SourceCite]) -> str:
    definitions = {f"[^{cite.sid}]: {cite.origin}" for cite in sources}
    lines = body.rstrip().splitlines()
    while lines and (not lines[-1].strip() or lines[-1] in definitions):
        _ = lines.pop()
    return "\n".join(lines).rstrip()


def init_vault(root: str | Path) -> Vault:
    root_path = Path(root)
    _ = root_path.mkdir(parents=True, exist_ok=True)
    for rel in VAULT_DIRS:
        _ = (root_path / rel).mkdir(parents=True, exist_ok=True)
    log_path, gitignore = root_path / "log.md", root_path / ".gitignore"
    if not log_path.exists():
        _ = log_path.write_text("", encoding="utf-8")
    if not gitignore.exists():
        _ = gitignore.write_text(GITIGNORE_BODY, encoding="utf-8")
    _ = root_path.chmod(0o700)
    if not (root_path / ".git").exists():
        _ = _git(root_path, "init", "-b", "main")
    try:
        _ = _git(root_path, "rev-parse", "-q", "--verify", "HEAD")
    except GitCommandError:
        _ = _commit_if_changed(root_path, INIT_MESSAGE)
    return Vault(root=root_path)


def _git_bytes(root: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
        }
    )
    argv = (
        "git",
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "-c",
        "commit.gpgsign=false",
        *args,
    )
    completed = subprocess.run(argv, cwd=root, capture_output=True, check=False, env=env)
    if completed.returncode != 0:
        raise GitCommandError(argv=args, stderr=completed.stderr.decode(errors="replace"))
    return completed.stdout


def _committed_bytes_match(root: Path, dest: Path) -> bool:
    try:
        relative = dest.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    try:
        return _git_bytes(root, "show", f"HEAD:{relative}") == dest.read_bytes()
    except GitCommandError:
        return False


def _write_compiled_marker(root: Path, page_id: str, dest: Path) -> None:
    compiled = root / ".sb" / "compiled"
    compiled.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = compiled / f"{page_id.replace('/', '_')}.sha"
    marker.write_text(hashlib.sha256(dest.read_bytes()).hexdigest(), encoding="utf-8")
    marker.chmod(0o600)


def _divert_to_proposed(root: Path, dest: Path, previous: str | None) -> bool:
    if previous is not None:
        return hashlib.sha256(dest.read_bytes()).hexdigest() != previous
    return not _committed_bytes_match(root, dest)


def _plan_writes(
    root: Path,
    planned: Sequence[tuple[Path, PageSpec]],
    ledger: CompiledHashLedger,
    compiled: tuple[str, str],
) -> tuple[tuple[int, int, int], list[tuple[Path, str, str, str]]]:
    stamp, updated = compiled
    stamp_parts = stamp.split("|", 2)
    package_stamp = stamp_parts[0]
    fallback_prompt = stamp_parts[1] if len(stamp_parts) >= 2 else "v1"
    fallback_model = stamp_parts[2] if len(stamp_parts) >= 3 else "unknown"
    n_pages = n_conflicts = n_proposals = 0
    jobs: list[tuple[Path, str, str, str]] = []
    conflicts_root = root / "conflicts"
    for dest, page in planned:
        prompt_version = page.prompt_version or fallback_prompt
        model_id = page.model_id or fallback_model
        text = _render(
            page,
            compiled_by=f"{package_stamp}|{prompt_version}|{model_id}",
            updated=updated,
        )
        if dest.is_file() and _divert_to_proposed(root, dest, ledger.last_compiled_hash(page.page_id)):
            slug = page.page_id.replace("/", "-")
            proposed = _safe_rel(root, Path("wiki/_proposed") / f"{slug}.md")
            if not (proposed.is_file() and proposed.read_text(encoding="utf-8") == text):
                jobs.append((proposed, text, "proposal", page.page_id))
            n_proposals += 1
            continue
        if dest.is_file() and dest.read_text(encoding="utf-8") == text:
            n_conflicts += dest.is_relative_to(conflicts_root)
            n_pages += not dest.is_relative_to(conflicts_root)
            continue
        kind = "conflict" if dest.is_relative_to(conflicts_root) else "page"
        jobs.append((dest, text, kind, page.page_id))
        n_conflicts += kind == "conflict"
        n_pages += kind == "page"
    return (n_pages, n_conflicts, n_proposals), jobs


def _restore(
    root: Path,
    snapshots: Sequence[tuple[Path, bytes | None]],
    log_path: Path,
    log_prev: bytes | None,
) -> None:
    for path, previous in snapshots:
        if previous is None and path.is_file():
            path.unlink()
        elif previous is not None:
            _ = path.write_bytes(previous)
    if log_prev is None and log_path.is_file():
        log_path.unlink()
    elif log_prev is not None:
        _ = log_path.write_bytes(log_prev)
    try:
        _ = _git(root, "reset", "-q", "HEAD")
    except GitCommandError:
        return


def _lint(root: Path, page: PageSpec) -> list[str]:
    reasons: list[str] = []
    if not page.body_md.strip():
        reasons.append(f"{page.page_id}: empty body")
    known = {cite.sid for cite in page.sources}
    for match in FOOTNOTE_RE.finditer(page.body_md):
        sid = match.group(1)
        if sid not in known:
            reasons.append(f"{page.page_id}: unresolved [^{sid}]")
    for cite in page.sources:
        digest = cite.hash
        if not digest or not (root / "raw" / digest[:2] / digest).is_file():
            reasons.append(f"{page.page_id}: missing CAS {digest}")
    return reasons


def _rel_for(page_id: str) -> Path:
    if not page_id or page_id.startswith("/") or ".." in page_id.split("/"):
        raise PathEscapeError(page_id=page_id)
    if page_id.startswith(("conflicts/", "daily/", "wiki/")):
        return Path(f"{page_id}.md")
    return Path("wiki") / f"{page_id}.md"


def _safe_rel(root: Path, rel: Path) -> Path:
    if rel.is_absolute() or ".." in rel.parts:
        raise PathEscapeError(page_id=str(rel))
    dest = (root / rel).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise PathEscapeError(page_id=str(rel))
    return dest


def _render_definitions(body: str, sources: Sequence[SourceCite]) -> str:
    """Deduplicate owned source definitions, leaving Markdown examples intact."""
    definitions = {cite.sid: f"[^{cite.sid}]: {cite.origin}" for cite in sources}
    lines = body.rstrip().splitlines()
    owned: dict[str, list[int]] = {}
    fence = ""
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
            continue
        if marker:
            fence = marker[1]
            continue
        match = re.match(r"^ {0,3}\[\^([^\]]+)\]: (.*)$", line)
        if not match or match[1] not in definitions:
            continue
        canonical = definitions[match[1]]
        value = line.lstrip(" ")
        origin = canonical.split(": ", 1)[1]
        native = f"[^{match[1]}]: sid={match[1]} origin={origin}"
        if (value == canonical or re.fullmatch(re.escape(canonical) + SPAN_SUFFIX_RE, value)
                or re.fullmatch(re.escape(native) + SPAN_SUFFIX_RE, value)):
            owned.setdefault(match[1], []).append(index)
    removed: set[int] = set()
    for sid, indices in owned.items():
        # Prefer the definition retaining the model's source span annotation.
        keep = next((i for i in indices if " span=" in lines[i]), indices[0])
        removed.update(i for i in indices if i != keep and
            lines[i].strip() in {definitions[sid], lines[keep].strip()})
    rendered = "\n".join(line for i, line in enumerate(lines) if i not in removed).rstrip()
    missing = "\n".join(value for sid, value in definitions.items() if sid not in owned)
    if missing:
        rendered += "\n\n" + missing
    return rendered


def _render(page: PageSpec, *, compiled_by: str, updated: str) -> str:
    if page.sensitivity not in {None, "public", "personal", "sensitive", "restricted"}:
        raise VaultLintError((f"{page.page_id}: invalid sensitivity",))
    sources: list[dict[str, str | list[str]]] = []
    for cite in page.sources:
        entry: dict[str, str | list[str]] = {
            "sid": cite.sid,
            "origin": cite.origin,
            "hash": cite.hash,
        }
        if cite.spans:
            entry["spans"] = list(cite.spans)
        sources.append(entry)
    payload: dict[str, object] = {
        "id": page.page_id,
        "title": page.title,
        "updated": updated,
        "compiled_by": compiled_by,
        "status": page.status,
        "sources": sources,
    }
    if page.derivation_key is not None:
        payload["derivation_key"] = page.derivation_key
    if page.sensitivity is not None:
        payload["sensitivity"] = page.sensitivity
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    body = _render_definitions(page.body_md, page.sources)
    return f"---\n{dumped}---\n\n{body}\n"


def _atomic_write(path: Path, text: str) -> None:
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _ = tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
        }
    )
    argv = (
        "git",
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "-c",
        "commit.gpgsign=false",
        *args,
    )
    completed = subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise GitCommandError(argv=args, stderr=completed.stderr)
    return completed.stdout


def _commit_if_changed(root: Path, message: str, paths: Sequence[Path] | None = None) -> str | None:
    if paths is None:
        _ = _git(root, "add", "-A")
    elif not paths:
        return None
    else:
        rels = [str(path.resolve().relative_to(root.resolve())) for path in paths]
        _ = _git(root, "add", "--", *rels)
    if _git(root, "diff", "--cached", "--name-only").strip() == "":
        return None
    _ = _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()
