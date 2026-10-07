"""Operational summaries with explicit time budgets and read-only SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, cast

from pydantic import TypeAdapter, ValidationError

from sb.backup_verification import instant
from sb.config import DEFAULT_CAPS, Config
from sb.effect_values import JsonInput
from sb.store.ledger import CURRENT_SCHEMA_VERSION
from sb.tombstone_snapshot import GENESIS_ROOT

_RUN_METADATA: Final = TypeAdapter[dict[str, str | None]](dict[str, str | None])


@dataclass(frozen=True)
class ReadinessPolicy:
    run_seconds: int = 48 * 3600
    backup_seconds: int = 48 * 3600
    request_seconds: int = 15 * 60
    failure_seconds: int = 48 * 3600

    @classmethod
    def from_config(cls, config: Config) -> ReadinessPolicy:
        table = config.raw.get("readiness", {})
        if not isinstance(table, dict):
            raise TypeError("invalid readiness policy")
        values: list[int] = []
        for key, default, multiplier in (
            ("max_run_age_hours", 48, 3600), ("max_backup_age_hours", 48, 3600),
            ("max_request_age_minutes", 15, 60), ("failure_window_hours", 48, 3600),
        ):
            value = table.get(key, default)
            if type(value) is not int or not 1 <= value <= 8760:
                raise ValueError("invalid readiness time budget")
            values.append(value * multiplier)
        return cls(*values)


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True, timeout=0.1)
    connection.row_factory = sqlite3.Row
    _ = connection.execute("PRAGMA query_only=ON")
    return connection


def ledger_checks(
    root: Path, now: datetime, policy: ReadinessPolicy,
    max_attempts: int = DEFAULT_CAPS["max_derivation_attempts"],
) -> tuple[dict[str, bool], dict[str, JsonInput]]:
    with closing(readonly(root / ".sb" / "ledger.db")) as connection:
        _ = connection.execute("BEGIN")
        version = cast(tuple[str] | None, connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone())
        row = cast(sqlite3.Row | None, connection.execute(
            "SELECT * FROM run ORDER BY started_at DESC,run_id DESC LIMIT 1"
        ).fetchone())
        failed = _count(connection, "SELECT count(*) FROM derivation WHERE status='failed'")
        held = _count(connection,
            "SELECT count(*) FROM derivation WHERE stage IN ('compile','conflict','brief') "
            + "AND status IN ('failed','pending') AND attempts>=?", (max_attempts,))
    try:
        last = None if row is None else _RUN_METADATA.validate_python(dict(row), strict=True)
    except ValidationError as exc:
        raise ValueError("invalid run metadata") from exc
    age: float | None = None
    time_valid = False
    if last is not None and isinstance(last.get("finished_at"), str):
        try:
            finished = instant(str(last["finished_at"]))
            age = (now - finished).total_seconds()
            time_valid = instant(str(last["started_at"])) <= finished <= now
        except (ValueError, OverflowError):
            pass
    checks = {"initialized": (root / ".git").is_dir(),
        "ledger_schema": version is not None and str(version[0]) == str(CURRENT_SCHEMA_VERSION),
        "last_run_success": last is not None and last.get("status") in {"ok", "capped"},
        "last_run_recent": time_valid and age is not None and age <= policy.run_seconds,
        "derivations_healthy": failed == 0, "derivations_held": held == 0}
    return checks, {"last_run": last, "last_run_age_seconds": age, "failed_derivations": failed, "held_derivations": held}


def request_checks(db: Path, now: datetime, policy: ReadinessPolicy) -> tuple[dict[str, bool], dict[str, JsonInput]]:
    with closing(readonly(db)) as connection:
        _ = connection.execute("BEGIN")
        counts = cast(list[tuple[str, int]], connection.execute(
            "SELECT state,count(*) AS count FROM requests GROUP BY state"
        ).fetchall())
        row = cast(tuple[str] | None, connection.execute(
            "SELECT accepted_at FROM requests WHERE state IN ('pending','processing') "
            + "ORDER BY julianday(accepted_at) LIMIT 1"
        ).fetchone())
        failures = _count(connection,
            "SELECT count(*) FROM requests WHERE state IN ('failed','expired','reapproval_required') "
            + "AND (julianday(updated_at)>=julianday(?) OR julianday(updated_at) IS NULL)",
            ((now - timedelta(seconds=policy.failure_seconds)).isoformat(),),
        )
        invalid = _count(connection,
            "SELECT count(*) FROM requests WHERE julianday(accepted_at) IS NULL "
            + "OR julianday(updated_at) IS NULL OR julianday(accepted_at)>julianday(updated_at) "
            + "OR julianday(updated_at)>julianday(?)", (now.isoformat(),)
        )
        high_water = cast(tuple[int, str] | None, connection.execute(
            "SELECT sequence,set_root FROM tombstone_replica ORDER BY sequence DESC LIMIT 1"
        ).fetchone())
    oldest = None if row is None else str(row[0])
    age = None if oldest is None else (now - instant(oldest)).total_seconds()
    return {"request_journal": True, "request_times": invalid == 0,
        "requests_progressing": age is None or 0 <= age <= policy.request_seconds,
        "requests_healthy": failures == 0}, {
        "requests": {item[0]: item[1] for item in counts},
        "oldest_request_at": oldest, "oldest_request_age_seconds": age,
        "recent_failed_requests": failures, "tombstone_high_water": tuple(high_water) if high_water else (0, GENESIS_ROOT)}


def generation_checks(db: Path, now: datetime, policy: ReadinessPolicy) -> dict[str, bool]:
    with closing(readonly(db)) as connection:
        pending = _count(connection,
            "SELECT count(*) FROM activations WHERE phase<>'proved' AND "
            + "(julianday(updated_at) IS NULL OR julianday(updated_at)<julianday(?) "
            + "OR julianday(updated_at)>julianday(?))",
            ((now - timedelta(seconds=policy.request_seconds)).isoformat(), now.isoformat()),
        )
    return {"generation_journal": True, "generation_cleanup": pending == 0}


def _count(connection: sqlite3.Connection, sql: str, parameters: tuple[str | int, ...] = ()) -> int:
    row = cast(tuple[int], connection.execute(sql, parameters).fetchone())
    return row[0]
