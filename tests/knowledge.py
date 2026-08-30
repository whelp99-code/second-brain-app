"""Temp-vault helper: register knowledge/approval in the durable registry."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sb.knowledge_registry import KnowledgeRegistry, KnowledgeState
from sb.search import committed_paths

_INDEX_PREFIXES: tuple[str, ...] = ("wiki/", "daily/", "conflicts/")


def registry_file(root: Path) -> Path:
    """Per-vault registry used by tests. Outside markdown, next to search.db."""
    return root / ".sb" / "knowledge-registry.sqlite"


def register_page(
    root: Path,
    page_id: str,
    *,
    knowledge_status: str = "ACTIVE",
    approval_status: str = "APPROVED",
    canonical: str = "",
    decided_by: str = "test",
    reason: str = "test register",
    source_hash: str = "",
) -> KnowledgeState:
    """Write one registry row. Does not edit vault markdown."""
    folder = root / ".sb"
    folder.mkdir(parents=True, exist_ok=True)
    return KnowledgeRegistry(registry_file(root)).put(
        page_id,
        knowledge_status=knowledge_status,
        approval_status=approval_status,
        canonical=canonical,
        decided_by=decided_by,
        reason=reason,
        source_hash=source_hash,
    )


def stamp_knowledge(
    root: Path,
    *,
    knowledge_status: str = "ACTIVE",
    approval_status: str = "APPROVED",
) -> None:
    """Register committed index pages. Does not parse body or write YAML."""
    for rel in committed_paths(root, _INDEX_PREFIXES):
        page_id = rel.removesuffix(".md")
        register_page(
            root,
            page_id,
            knowledge_status=knowledge_status,
            approval_status=approval_status,
        )


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
