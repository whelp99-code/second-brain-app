"""Temp-vault helper: stamp structured knowledge/approval YAML, then commit."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_INDEX_FOLDERS: tuple[str, ...] = ("wiki", "daily", "conflicts")


def stamp_knowledge(
    root: Path,
    *,
    knowledge_status: str = "ACTIVE",
    approval_status: str = "APPROVED",
) -> None:
    """Insert structured frontmatter keys into committed pages that lack them.

    Does not parse body prose. Skips wiki/_proposed. Commits only when files change.
    """
    changed: list[Path] = []
    for folder in _INDEX_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if "_proposed" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            rest = text[3:].lstrip("\n")
            end = rest.find("\n---")
            if end < 0:
                continue
            block = rest[:end]
            keys = {line.partition(":")[0].strip() for line in block.splitlines()}
            if "knowledge_status" in keys:
                continue
            stamped = (
                block.rstrip()
                + f"\nknowledge_status: {knowledge_status}\napproval_status: {approval_status}\n"
            )
            path.write_text("---\n" + stamped + rest[end:], encoding="utf-8")
            changed.append(path)
    if not changed:
        return
    _git_commit(root, "test: stamp knowledge_status")


def commit_page(root: Path, rel: str, text: str, message: str = "test: add knowledge page") -> None:
    """Write one vault-relative markdown file and commit it."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(text, encoding="utf-8")
    _git_commit(root, message)


def _git_commit(root: Path, message: str) -> None:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    add = subprocess.run(
        ["git", "add", "-A"], cwd=root, capture_output=True, text=True, check=False, env=env
    )
    if add.returncode != 0:
        raise AssertionError(add.stderr)
    committed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=second-brain-test",
            "-c",
            "user.email=sb-test@local",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            message,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if committed.returncode != 0:
        raise AssertionError(committed.stderr)
