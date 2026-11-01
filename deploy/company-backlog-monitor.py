"""Publish a private aggregate company-backlog snapshot; never drain candidates."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypedDict, cast

SQL_PATH: Final = Path(__file__).with_name("company-reader-drain.sql")
THRESHOLD_SECONDS: Final = 86_400
type Status = Literal["CLEAR", "PENDING", "STALE", "UNKNOWN", "ERROR"]
type ObservationRow = tuple[str, str, int, int, int, str | None, float | None, int]


class Snapshot(TypedDict):
    schema_version: Literal[1]
    observed_at: str
    status: Status
    pending_count: int | None
    pending_received_last_24h: int | None
    oldest_pending_received_at: str | None
    oldest_pending_age_seconds: float | None
    pending_age_unknown_count: int | None
    invalid_receipt_time_count: int | None
    threshold_seconds: int
    error_code: str | None
    drain_authorized: Literal[False]


def error_snapshot(now: datetime, code: str) -> Snapshot:
    return {
        "schema_version": 1, "observed_at": now.isoformat(timespec="milliseconds"),
        "status": "ERROR", "pending_count": None, "pending_received_last_24h": None,
        "oldest_pending_received_at": None, "oldest_pending_age_seconds": None,
        "pending_age_unknown_count": None, "invalid_receipt_time_count": None,
        "threshold_seconds": THRESHOLD_SECONDS, "error_code": code, "drain_authorized": False,
    }


def inspect(database: Path, now: datetime | None = None) -> Snapshot:
    """Reuse the shipped SQL, selecting only aggregate columns in one readonly transaction."""
    instant = datetime.now(UTC) if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    instant = instant.astimezone(UTC)
    try:
        source = database.resolve(strict=True)
        query = SQL_PATH.read_text().rstrip().removesuffix(";")
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            _ = db.execute("PRAGMA query_only=ON")
            _ = db.execute("BEGIN")
            rows: list[ObservationRow] = db.execute(
                """SELECT observed_at,monitor_state,pending_total,pending_received_last_24h,
                pending_age_unknown,oldest_pending_received_at,oldest_pending_age_seconds,
                invalid_receipt_time_count FROM (""" + query + ")",
                {"observed_at": instant.isoformat(timespec="milliseconds")},
            ).fetchall()
            db.rollback()
    except (OSError, sqlite3.Error):
        # Never include exception text: paths or malformed database contents may be private.
        return error_snapshot(instant, "DATABASE_READ_FAILED")
    observed, raw_status, count, recent, unknown, oldest, age, invalid = rows[0]
    status: Status
    if count > 0 and age is not None and age >= THRESHOLD_SECONDS:
        status = "STALE"
    else:
        match raw_status:
            case "clear":
                status = "CLEAR"
            case "pending":
                status = "PENDING"
            case "unknown" | "invalid_clock":
                status = "UNKNOWN"
            case "stale":
                status = "STALE"
            case _:
                return error_snapshot(instant, "QUERY_RESULT_INVALID")
    return {
        "schema_version": 1, "observed_at": observed, "status": status,
        "pending_count": count, "pending_received_last_24h": recent,
        "oldest_pending_received_at": oldest, "oldest_pending_age_seconds": age,
        "pending_age_unknown_count": unknown, "invalid_receipt_time_count": invalid,
        "threshold_seconds": THRESHOLD_SECONDS, "error_code": None, "drain_authorized": False,
    }


def publish(output: Path, line: str) -> bool:
    """Publish atomically; False means visible, but directory durability is unconfirmed."""
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".backlog-", dir=output.parent)
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            _ = stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        published = True
    finally:
        if not published:
            temporary.unlink(missing_ok=True)
    # Replacement is the visibility commit point. Never reinterpret later failures
    # as an unpublished observation or attempt a second write to the failing storage.
    try:
        directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        return False
    return True


def run(database: Path, output: Path, now: datetime | None = None) -> int:
    instant = datetime.now(UTC) if now is None else now
    # Never let a mistaken result path replace the DB or its sidecars/source files.
    try:
        conflict = output.resolve().is_relative_to(database.resolve().parent)
    except OSError:
        snapshot = error_snapshot(instant, "PATH_RESOLUTION_FAILED")
        print(json.dumps(snapshot, separators=(",", ":"), allow_nan=False))
        return 1
    if conflict:
        snapshot = error_snapshot(instant, "OUTPUT_PATH_CONFLICT")
        print(json.dumps(snapshot, separators=(",", ":"), allow_nan=False))
        return 1
    snapshot = inspect(database, instant)
    line = json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        durable = publish(output, line)
    except OSError:
        snapshot = error_snapshot(instant, "RESULT_PUBLISH_FAILED")
        line = json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n"
        print(line, end="")
        return 1
    print(line, end="")
    if not durable:
        print("RESULT_DURABILITY_UNCONFIRMED", file=sys.stderr)
        return 1
    return 1 if snapshot["status"] == "ERROR" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--database", type=Path, required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    previous = os.umask(0o077)
    try:
        return run(cast(Path, args.database), cast(Path, args.output))
    finally:
        _ = os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())
