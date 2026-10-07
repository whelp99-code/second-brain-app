"""Read-only operational snapshots and explicit retry/migration operations."""

from pathlib import Path

from sb.config import Config
from sb.ops_models import (
    BatchSnapshot,
    FailedDerivationSnapshot,
    MigrationSnapshot,
    OperationError,
    RunSnapshot,
    StageSnapshot,
    StatusSnapshot,
)
from sb.ops_sql import read_stages
from sb.ops_support import git_value, safe_detail
from sb.store import DerivStatus, load_ledger_tables, run_time_key
from sb.store.ledger import CURRENT_SCHEMA_VERSION, Ledger, ledger_schema_version, migrate_ledger


def status_snapshot(config: Config) -> StatusSnapshot:
    root = Path(config.vault_root)
    db = root / ".sb" / "ledger.db"
    derivations: dict[str, int] = {status.value: 0 for status in DerivStatus}
    runs: dict[str, int] = {}
    failed: list[FailedDerivationSnapshot] = []
    failed_by_stage: dict[str, int] = {}
    last_run: RunSnapshot | None = None
    recent_stages: list[StageSnapshot] = []
    last_batch: BatchSnapshot | None = None
    if db.is_file():
        last_batch, recent_stages = read_stages(db)
        tables = load_ledger_tables(db)
        for row in tables.derivations.values():
            derivations[row.status] = derivations.get(row.status, 0) + 1
            if row.status == DerivStatus.FAILED.value:
                failed_by_stage[row.stage] = failed_by_stage.get(row.stage, 0) + 1
            if row.status == DerivStatus.FAILED.value and len(failed) < 20:
                failed.append(
                    {
                        "key": row.deriv_key,
                        "stage": row.stage,
                        "attempts": row.attempts,
                        "error": safe_detail(row.error),
                        "retry_hold_reason": "BRIEF_REPLAY_INPUTS_UNAVAILABLE"
                        if row.stage == "brief" else None,
                    }
                )
        ordered = sorted(tables.runs.values(), key=lambda row: (run_time_key(row.started_at), row.run_id))
        for row in ordered:
            runs[row.status] = runs.get(row.status, 0) + 1
        if ordered:
            latest = ordered[-1]
            last_run = {
                "run_id": latest.run_id, "started_at": latest.started_at,
                "finished_at": latest.finished_at, "git_commit": latest.git_commit,
                "status": latest.status,
            }
    counts = {
        name: sum(1 for _ in (root / name).rglob("*.md")) if (root / name).is_dir() else 0
        for name in ("wiki", "daily", "conflicts")
    }
    raw_files = (
        [path for path in (root / "raw").rglob("*") if path.is_file()]
        if (root / "raw").is_dir()
        else []
    )
    return {
        "vault_root": str(root),
        "initialized": (root / ".git").is_dir(),
        "schema_version": ledger_schema_version(db),
        "schema_current": CURRENT_SCHEMA_VERSION,
        "git_head": git_value(root, "rev-parse", "HEAD") if root.is_dir() else None,
        "git_clean": git_value(root, "status", "--porcelain") == ""
        if (root / ".git").is_dir()
        else False,
        "last_run": last_run,
        "recent_stages": recent_stages,
        "last_batch": last_batch,
        "run_counts": runs,
        "derivation_counts": derivations,
        "failed_derivations": failed,
        "failed_by_stage": failed_by_stage,
        "failed_details_omitted": sum(failed_by_stage.values()) - len(failed),
        "pages": {"wiki": counts["wiki"], "daily": counts["daily"], "conflicts": counts["conflicts"]},
        "raw": {"files": len(raw_files), "bytes": sum(path.stat().st_size for path in raw_files)},
    }



def retry_failed(
    vault_root: Path | str,
    *,
    stage: str | None = None,
    limit: int | None = None,
) -> int:
    with Ledger(vault_root) as ledger:
        selected = list(ledger.list_derivations(status=DerivStatus.FAILED.value, stage=stage))
        if limit is not None:
            selected = selected[:max(limit, 0)]
        if any(row.stage == "brief" for row in selected):
            # Brief execution rebuilds today's key; it cannot replay arbitrary
            # historical keys without their frozen inputs and target date.
            # Reject the whole selection before resetting any other attempts.
            raise OperationError(
                "BRIEF_REPLAY_INPUTS_UNAVAILABLE: historical brief retry is held; "
                + "failed rows and attempts are preserved"
            )
        return ledger.retry_failed(stage=stage, limit=limit, reset_attempts=True)



def migrate_status(vault_root: Path | str, *, apply: bool) -> MigrationSnapshot:
    path = Path(vault_root) / ".sb" / "ledger.db"
    before = ledger_schema_version(path)
    backup = migrate_ledger(path, backup=True) if apply else None
    after = ledger_schema_version(path)
    return {
        "before": before,
        "after": after,
        "current": CURRENT_SCHEMA_VERSION,
        "pending": max(CURRENT_SCHEMA_VERSION - after, 0),
        "backup": str(backup) if backup is not None else None,
    }
