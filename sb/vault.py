"""Sole vault filesystem writer and sole git committer."""

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
    """Last compiled content hash per page_id."""

    def last_compiled_hash(self, page_id: str) -> str | None:
        """Return sha256 hex of the last compiled bytes, or None."""


@dataclass(frozen=True, slots=True)
class VaultLintError(Exception):
    """Pre-commit lint failed; the vault tree must remain unchanged."""

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
    """Initialized vault root; sole writer of wiki/daily/conflicts/log.md."""

    root: Path

    def write_pages(
        self, pages: Sequence[PageSpec], run_id: str, ledger: CompiledHashLedger
    ) -> WriteResult:
        """Lint, atomically write cited pages, and commit when the tree changes."""
        reasons = tuple(reason for page in pages for reason in _lint(self.root, page))
        if reasons:
            raise VaultLintError(reasons=reasons)
        planned = [(_safe_rel(self.root, _rel_for(page.page_id)), page) for page in pages]
        n_pages = n_conflicts = n_proposals = 0
        written: list[Path] = []
        try:
            version = metadata.version("second-brain")
        except metadata.PackageNotFoundError:
            version = "0.1.0"
        stamp = f"sb/{version}|v1|unknown"
        updated = datetime.now(UTC).date().isoformat()
        for dest, page in planned:
            text = _render(page, compiled_by=stamp, updated=updated)
            if dest.is_file():
                current = hashlib.sha256(dest.read_bytes()).hexdigest()
                if ledger.last_compiled_hash(page.page_id) != current:
                    slug = page.page_id.replace("/", "-")
                    proposed = _safe_rel(self.root, Path("wiki/_proposed") / f"{slug}.md")
                    _atomic_write(proposed, text)
                    self.append_log(f"human-edit: {page.page_id} -> wiki/_proposed/{slug}.md")
                    written.extend((proposed, self.root / "log.md"))
                    n_proposals += 1
                    continue
            _atomic_write(dest, text)
            written.append(dest)
            if dest.is_relative_to(self.root / "conflicts"):
                n_conflicts += 1
            else:
                n_pages += 1
        message = f"sb: run {run_id} ({n_pages} pages, {n_conflicts} conflicts, {n_proposals} proposals)"
        return WriteResult(
            n_pages, n_conflicts, n_proposals, _commit_if_changed(self.root, message, written)
        )

    def append_log(self, line: str) -> None:
        """Append one line to tracked log.md. Does not commit."""
        path = self.root / "log.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        _atomic_write(path, f"{existing}{line.rstrip()}\n")

    def rollback(self, run_id: str) -> None:
        """Revert the commit whose message starts with `sb: run <run_id>`."""
        sha = _git(
            self.root, "log", "-F", "--grep", f"sb: run {run_id} ", "--format=%H", "-1"
        ).strip()
        if not sha:
            raise RunCommitNotFoundError(run_id=run_id)
        _ = _git(self.root, "revert", "--no-edit", sha)


def init_vault(root: str | Path) -> Vault:
    """Create vault layout, lock down perms, git-init, and make the initial commit."""
    root_path = Path(root)
    _ = root_path.mkdir(parents=True, exist_ok=True)
    for rel in VAULT_DIRS:
        _ = (root_path / rel).mkdir(parents=True, exist_ok=True)
    log_path = root_path / "log.md"
    if not log_path.exists():
        _ = log_path.write_text("", encoding="utf-8")
    gitignore = root_path / ".gitignore"
    if not gitignore.exists():
        _ = gitignore.write_text(GITIGNORE_BODY, encoding="utf-8")
    _ = root_path.chmod(0o700)
    if not (root_path / ".git").exists():
        _ = _git(root_path, "init", "-b", "main")
    if not _has_head(root_path):
        _ = _commit_if_changed(root_path, INIT_MESSAGE)
    return Vault(root=root_path)


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
        entry: dict[str, str | list[str]] = {
            "sid": cite.sid,
            "origin": cite.origin,
            "hash": cite.hash,
        }
        if cite.spans:
            entry["spans"] = list(cite.spans)
        sources.append(entry)
    payload = {
        "id": page.page_id,
        "title": page.title,
        "updated": updated,
        "compiled_by": compiled_by,
        "status": page.status,
        "sources": sources,
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
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = BOT_NAME
    env["GIT_AUTHOR_EMAIL"] = BOT_EMAIL
    env["GIT_COMMITTER_NAME"] = BOT_NAME
    env["GIT_COMMITTER_EMAIL"] = BOT_EMAIL
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
    completed = subprocess.run(
        argv, cwd=root, capture_output=True, text=True, check=False, env=env
    )
    if completed.returncode != 0:
        raise GitCommandError(argv=args, stderr=completed.stderr)
    return completed.stdout


def _has_head(root: Path) -> bool:
    try:
        _ = _git(root, "rev-parse", "-q", "--verify", "HEAD")
    except GitCommandError:
        return False
    return True


def _commit_if_changed(
    root: Path, message: str, paths: Sequence[Path] | None = None
) -> str | None:
    if paths is None:
        _ = _git(root, "add", "-A")
    elif paths:
        rels = [str(path.resolve().relative_to(root.resolve())) for path in paths]
        _ = _git(root, "add", "--", *rels)
    else:
        return None
    if _git(root, "diff", "--cached", "--name-only").strip() == "":
        return None
    _ = _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()
