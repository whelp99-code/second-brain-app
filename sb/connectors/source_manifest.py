"""Opt-in, per-root source inventory for installer configuration.

This inventory does not scan source bodies or implicitly enable any source. An
operator must select the available rows and approve their policies before use.
Classification stays in ``[source_access]``; a source body cannot set it.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

SourceState = Literal["available", "unavailable"]
HERMES_INCLUDE: str = "memory/**/*.md,memory.md"
HERMES_EXCLUDE: str = "config/**,plugins/**,skills/**"
_DIARY_ROOTS: frozenset[str] = frozenset({"config", "plugins", "skills"})


@dataclass(frozen=True, slots=True)
class SourceRoot:
    source_id: str
    adapter: str
    root: Path
    state: SourceState
    scope: str
    # The source id is root-qualified, so neither its cursor nor its observations
    # can silently inherit the old family-wide ledger identity.

    def config_row(self) -> dict[str, str]:
        if self.state != "available":
            raise ValueError("unavailable sources cannot be installed")
        row = {
            "id": self.source_id,
            "adapter": self.adapter,
            "root": str(self.root),
            "scope": self.scope,
            "llm_policy": "deny",
            "sensitive": "mask",
        }
        if self.scope == "hermes-memory":
            row["include"] = HERMES_INCLUDE
            row["exclude"] = HERMES_EXCLUDE
        if self.scope == "ai-session":
            row["session_profile"] = "facts-v1"
        if self.scope == "project-record":
            row["record_identity"] = "v1"
        return row


# Candidate paths are metadata only. No auto-probing happens in the ingest path.
CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    ("claude", "claude-sessions", "~/.claude/projects", "ai-session"),
    ("codex", "codex-sessions", "~/.codex/sessions", "ai-session"),
    ("omo", "omo-sessions", "~/.omo/agent/sessions", "ai-session"),
    ("senpi", "omo-sessions", "~/.senpi/agent/sessions", "ai-session"),
    ("pi", "omo-sessions", "~/.pi/agent/sessions", "ai-session"),
    ("opencode", "opencode-sessions", "~/.local/share/opencode", "ai-session"),
    ("opencode", "opencode-sessions", "~/.opencode", "ai-session"),
    ("gjc", "gjc-sessions", "~/.gjc/exports", "ai-session"),
    ("hermes", "markdown-vault", "~/.hermes", "hermes-memory"),
    ("dev-wiki", "markdown-vault", "~/dev-wiki", "development-memory"),
    ("project", "project-records", "~/exports/project", "project-record"),
    ("orca", "orca-records", "~/exports/orca", "project-record"),
)


def source_id(family: str, root: Path) -> str:
    """Use a path-bound id even if two roots contain identical bytes."""
    resolved = root.expanduser().absolute()
    suffix = sha256(str(resolved).encode()).hexdigest()[:16]
    return f"{family}-{suffix}"


def inventory(
    candidates: tuple[tuple[str, str, str, str], ...] = CANDIDATES,
) -> tuple[SourceRoot, ...]:
    """Include missing roots as unavailable, never as a successful empty scan."""
    rows: list[SourceRoot] = []
    for family, adapter, path, scope in candidates:
        root = Path(path).expanduser()
        state: SourceState = "available" if root.is_dir() else "unavailable"
        rows.append(SourceRoot(source_id(family, root), adapter, root, state, scope))
    return tuple(rows)


def installer_source_config(rows: tuple[SourceRoot, ...]) -> str:
    """Render only existing approved candidates as independent TOML source rows."""
    blocks: list[str] = []
    for source in rows:
        if source.state != "available":
            continue
        row = source.config_row()
        blocks.append(
            "[[sources]]\n"
            + "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in row.items())
        )
    return "\n".join(blocks)


def discovery_path_allowed(source_name: str, relative_path: str) -> bool:
    """Fixed manifest scope for hermes memory and dev-wiki markdown."""
    if source_name == "hermes":
        return _matches(relative_path, _csv(HERMES_INCLUDE)) and not _matches(
            relative_path, _csv(HERMES_EXCLUDE)
        )
    if source_name == "dev-wiki":
        return relative_path.endswith(".md") and not _diary_root(relative_path)
    return True


def _csv(patterns: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in patterns.split(",") if part.strip())


def _diary_root(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    return bool(parts) and parts[0] in _DIARY_ROOTS


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_match(path, pattern) for pattern in patterns)


def _pattern_match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    collapsed = pattern.replace("/**/", "/")
    return collapsed != pattern and fnmatch.fnmatchcase(path, collapsed)
