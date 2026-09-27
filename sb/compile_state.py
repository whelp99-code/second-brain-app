"""Read-only knowledge registry status and optional search projection."""

from typing import TypedDict

from sb.config import Config


class CompileStateReport(TypedDict):
    dry_run: bool
    state_report: bool
    vault_written: bool
    status_created: bool
    projected: bool
    projection_mode: str
    registry_path: str
    pages: list[dict[str, str | int]]
    counts: dict[str, int]


def compile_state_report(
    config: Config,
    *,
    dry_run: bool = False,
    project: bool = False,
) -> CompileStateReport:
    """Read the knowledge registry. Never write the vault. Never create status rows."""
    from pathlib import Path

    from sb.knowledge_registry import KnowledgeRegistry
    from sb.search import SearchIndex, resolve_registry_path

    root = Path(config.vault_root)
    explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
    path = resolve_registry_path(root, explicit)
    registry = KnowledgeRegistry(path)
    states = registry.read_snapshot()
    counts: dict[str, int] = {}
    for state in states:
        counts[state.knowledge_status] = counts.get(state.knowledge_status, 0) + 1
    projected = False
    if project and not dry_run:
        SearchIndex(vault_root=root, registry_path=path).project()
        projected = True
    return {
        "dry_run": dry_run,
        "state_report": True,
        "vault_written": False,
        "status_created": False,
        "projected": projected,
        "projection_mode": "read-time" if (root / "generation.json").is_file() else "index",
        "registry_path": str(path),
        "pages": [state.as_dict() for state in states],
        "counts": counts,
    }
