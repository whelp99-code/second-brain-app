"""Typed, read-only SQL boundaries for operational history and orphan counts."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from sb.ops_models import BatchSnapshot, StageSnapshot
from sb.ops_support import safe_detail
from sb.sqlite_values import OPTIONAL_INTEGER_ROW
from sb.store import run_time_key

type BatchRow = tuple[str, str, str, str | None, int, int, int]
type StageRow = tuple[str, str, str, int, str | None]
type StageHistory = tuple[BatchSnapshot | None, list[StageSnapshot]]
_BATCH: Final = TypeAdapter[BatchRow | None](BatchRow | None)
_STAGES: Final = TypeAdapter[list[StageRow]](list[StageRow])


def read_stages(db: Path) -> StageHistory:
    """Read the latest batch and ten recent stages without migrating the ledger."""
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.create_function("sb_run_time", 1, run_time_key, deterministic=True)
        exists = OPTIONAL_INTEGER_ROW.validate_python(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='run_stage'"
        ).fetchone(), strict=True)
        if exists is None:
            return None, []
        batch = _BATCH.validate_python(conn.execute(
            "SELECT run_id,status,started_at,finished_at,attempted,written,errors "
            + "FROM run_stage WHERE stage='batch' "
            + "ORDER BY sb_run_time(started_at) DESC,run_id DESC LIMIT 1"
        ).fetchone(), strict=True)
        rows = _STAGES.validate_python(conn.execute(
            "SELECT run_id,stage,status,errors,detail FROM run_stage "
            + "ORDER BY sb_run_time(started_at) DESC,run_id DESC LIMIT 10"
        ).fetchall(), strict=True)
    last_batch: BatchSnapshot | None = None
    if batch is not None:
        last_batch = {
            "run_id": batch[0], "status": batch[1], "started_at": batch[2],
            "finished_at": batch[3], "stages_attempted": batch[4],
            "written": batch[5], "errors": batch[6],
        }
    stages: list[StageSnapshot] = [
        {
            "run_id": row[0], "stage": row[1], "status": row[2], "errors": row[3],
            "error": safe_detail(row[4]) if row[1] != "batch" else "",
            "detail": safe_detail(row[4]) if row[1] == "batch" else "",
        }
        for row in rows
    ]
    return last_batch, stages


def activated_orphan_count(journal: Path, current_id: str) -> int:
    uri = journal.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        try:
            fetched = OPTIONAL_INTEGER_ROW.validate_python(connection.execute(
                "SELECT count(*) FROM activations WHERE phase = 'activated' AND generation_id != ?",
                (current_id,),
            ).fetchone(), strict=True)
        except ValidationError as exc:
            raise sqlite3.Error("activation count is not an integer") from exc
    return 0 if fetched is None else fetched[0]
