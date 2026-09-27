"""Read-only vault health checks and activation journal diagnostics."""

import shutil
import sqlite3
import stat
from pathlib import Path

from sb.config import Config
from sb.ops_models import DoctorCheck
from sb.ops_sql import activated_orphan_count
from sb.ops_support import git_value, package_version
from sb.pipeline import audit_citations
from sb.store import LedgerCorrupt, assert_ledger_integrity
from sb.store.ledger import CURRENT_SCHEMA_VERSION, ledger_schema_version


def doctor(config: Config) -> tuple[DoctorCheck, ...]:
    root = Path(config.vault_root)
    checks: list[DoctorCheck] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append(DoctorCheck(name, status, detail))

    add("python", "pass", f"Python runtime available; app {package_version()}")
    add("git", "pass" if shutil.which("git") else "fail", shutil.which("git") or "git not found")
    if not root.is_dir():
        add("vault", "fail", f"vault missing: {root}")
        return tuple(checks)
    mode = stat.S_IMODE(root.stat().st_mode)
    add("vault", "pass" if mode & 0o077 == 0 else "warn", f"path={root} mode={oct(mode)}")
    add(
        "git-repository",
        "pass" if (root / ".git").is_dir() else "fail",
        "initialized" if (root / ".git").is_dir() else "missing .git",
    )
    db = root / ".sb" / "ledger.db"
    if db.is_file():
        try:
            assert_ledger_integrity(db)
            version = ledger_schema_version(db)
            add(
                "ledger",
                "pass" if version == CURRENT_SCHEMA_VERSION else "warn",
                f"schema={version}/{CURRENT_SCHEMA_VERSION}",
            )
        except (LedgerCorrupt, OSError, sqlite3.Error) as exc:
            add("ledger", "fail", str(exc))
    else:
        add("ledger", "warn", "ledger not created yet")
    reasons = audit_citations(root)
    add(
        "citations",
        "pass" if not reasons else "fail",
        "ok" if not reasons else "; ".join(reasons[:5]),
    )
    for source in config.source_roots:
        path = source.get("root")
        if not path:
            continue
        source_path = Path(path)
        status = "pass" if source_path.is_dir() and not source_path.is_symlink() else "fail"
        add(
            f"source:{source.get('id', source.get('adapter', 'unknown'))}", status, str(source_path)
        )
    if root.is_symlink():
        try:
            from sb.generation_runtime_models import generation_runtime_paths
            from sb.generations import GenerationStore
            paths = generation_runtime_paths(config)
            manifest = GenerationStore.read_manifest(paths.active.resolve())
            valid = (git_value(root, "rev-parse", "HEAD") == manifest.head
                     and git_value(root, "rev-parse", "HEAD^{tree}") == manifest.tree)
            add("generation", "pass" if valid else "fail", manifest.generation_id)
            journal = paths.state / "generation-journal.db"
            if journal.is_file():
                try:
                    orphans = activated_orphan_count(journal, manifest.generation_id)
                    add(
                        "activation-orphans",
                        "warn" if orphans else "pass",
                        f"count={orphans}" if orphans else "none",
                    )
                except sqlite3.Error as exc:
                    add("activation-orphans", "warn", type(exc).__name__)
        except (OSError, RuntimeError, ValueError) as exc:
            add("generation", "fail", str(exc))
    command = config.llm.argv_template[0] if config.llm.argv_template else ""
    llm_status = "pass" if command and shutil.which(command) else "warn"
    add(
        "llm-cli",
        llm_status,
        command if llm_status == "pass" else f"not found: {command or '<empty>'}",
    )
    scheduler = Path(__file__).resolve().parent.parent / "deploy" / "systemd"
    add("scheduler-assets", "pass" if scheduler.is_dir() else "warn", str(scheduler))
    return tuple(checks)
