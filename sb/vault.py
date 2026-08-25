from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Final, Protocol, override

import yaml

from sb.contracts import PageSpec

BOT_NAME: Final = "second-brain-bot"
BOT_EMAIL: Final = "sb@local"
GITIGNORE_BODY: Final = "raw/\n.sb/\n"
INIT_MESSAGE: Final = "sb: init vault"
FOOTNOTE_RE: Final = re.compile(r"\[\^([^\]]+)\]")
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


@dataclass(frozen=True, slots=True)
class Vault:
    root: Path

    def write_pages(
        self,
        pages: Sequence[PageSpec],
        run_id: str,
        ledger: CompiledHashLedger,
        *,
        log_line: str | None = None,
    ) -> WriteResult:
        reasons = tuple(reason for page in pages for reason in _lint(self.root, page))
        if reasons:
            raise VaultLintError(reasons=reasons)
        planned = [(_safe_rel(self.root, _rel_for(page.page_id)), page) for page in pages]
        try:
            version = metadata.version("second-brain")
        except metadata.PackageNotFoundError:
            version = "0.1.0"
        counts, jobs = _plan_writes(
            self.root, planned, ledger,
            (f"sb/{version}|v1|unknown", datetime.now(UTC).date().isoformat()),
        )
        n_pages, n_conflicts, n_proposals = counts
        if not jobs:
            return WriteResult(n_pages, n_conflicts, n_proposals, None)
        log_path = self.root / "log.md"
        log_prev = log_path.read_bytes() if log_path.is_file() else None
        snapshots = tuple((dest, dest.read_bytes() if dest.is_file() else None) for dest, *_ in jobs)
        written: list[Path] = []
        try:
            for dest, text, kind, page_id in jobs:
                _atomic_write(dest, text)
                written.append(dest)
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
        return WriteResult(n_pages, n_conflicts, n_proposals, commit)

    def append_log(self, line: str) -> None:
        path = self.root / "log.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        _atomic_write(path, f"{existing}{line.rstrip()}\n")

    def rollback(self, run_id: str) -> None:
        sha = _git(
            self.root, "log", "-F", "--grep", f"sb: run {run_id} ", "--format=%H", "-1"
        ).strip()
        if not sha:
            raise RunCommitNotFoundError(run_id=run_id)
        _ = _git(self.root, "revert", "--no-edit", sha)


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


def _plan_writes(
    root: Path,
    planned: Sequence[tuple[Path, PageSpec]],
    ledger: CompiledHashLedger,
    compiled: tuple[str, str],
) -> tuple[tuple[int, int, int], list[tuple[Path, str, str, str]]]:
    stamp, updated = compiled
    n_pages = n_conflicts = n_proposals = 0
    jobs: list[tuple[Path, str, str, str]] = []
    conflicts_root = root / "conflicts"
    for dest, page in planned:
        text = _render(page, compiled_by=stamp, updated=updated)
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() != ledger.last_compiled_hash(
            page.page_id
        ):
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
    root: Path, snapshots: Sequence[tuple[Path, bytes | None]], log_path: Path, log_prev: bytes | None
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


def _render(page: PageSpec, *, compiled_by: str, updated: str) -> str:
    sources: list[dict[str, str | list[str]]] = []
    for cite in page.sources:
        entry: dict[str, str | list[str]] = {"sid": cite.sid, "origin": cite.origin, "hash": cite.hash}
        if cite.spans:
            entry["spans"] = list(cite.spans)
        sources.append(entry)
    payload = {
        "id": page.page_id, "title": page.title, "updated": updated,
        "compiled_by": compiled_by, "status": page.status, "sources": sources,
    }
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    definitions = "\n".join(f"[^{cite.sid}]: {cite.origin}" for cite in page.sources)
    body = page.body_md.rstrip()
    if definitions:
        body = f"{body}\n\n{definitions}"
    return f"---\n{dumped}---\n\n{body}\n"


def _atomic_write(path: Path, text: str) -> None:
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _ = tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL,
        "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL,
    })
    argv = ("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
            "-c", "commit.gpgsign=false", *args)
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
