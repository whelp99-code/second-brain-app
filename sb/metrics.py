"""Bounded local operational metrics that never store prompts or source content."""

from __future__ import annotations

import fcntl
import json
import math
import os
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from typing_extensions import TypedDict

from sb.vault_owner import require_vault_owner

MAX_METRICS_BYTES: Final = 10 * 1024 * 1024
KEEP_ROWS: Final = 10_000


class MetricSummaryDict(TypedDict, closed=True):
    total: int
    failures: int
    commands: dict[str, int]
    average_ms: float
    p95_ms: float


@dataclass(frozen=True, slots=True)
class MetricSummary:
    total: int
    failures: int
    commands: dict[str, int]
    average_ms: float
    p95_ms: float

    def as_dict(self) -> MetricSummaryDict:
        return {
            "total": self.total,
            "failures": self.failures,
            "commands": self.commands,
            "average_ms": self.average_ms,
            "p95_ms": self.p95_ms,
        }


def record_command(root: Path | str, command: str, exit_code: int, duration_ms: float) -> None:
    """Append one content-free command metric under an exclusive file lock."""
    vault = Path(root)
    require_vault_owner(vault)
    folder = vault / ".sb"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "metrics.jsonl"
    row = {
        "at": datetime.now(UTC).isoformat(),
        "command": command,
        "exit_code": int(exit_code),
        "duration_ms": round(max(float(duration_ms), 0.0), 3),
    }
    with _locked(path):
        _rotate(path)
        with path.open("a", encoding="utf-8") as handle:
            _ = handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def summary(root: Path | str, limit: int = 1000) -> MetricSummary:
    """Summarize the newest valid rows, ignoring malformed or partial records."""
    path = Path(root) / ".sb" / "metrics.jsonl"
    if not path.is_file() or limit <= 0:
        return MetricSummary(0, 0, {}, 0.0, 0.0)
    try:
        raw_rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return MetricSummary(0, 0, {}, 0.0, 0.0)
    commands: Counter[str] = Counter()
    failures = 0
    durations: list[float] = []
    total = 0
    for raw in raw_rows[-limit:]:
        loaded = _json_object(raw)
        if loaded is None:
            continue
        command = loaded.get("command")
        exit_code = loaded.get("exit_code")
        duration = loaded.get("duration_ms")
        if not isinstance(command, str) or not isinstance(exit_code, int):
            continue
        total += 1
        commands[command] += 1
        if exit_code != 0:
            failures += 1
        if isinstance(duration, int | float) and not isinstance(duration, bool):
            durations.append(max(float(duration), 0.0))
    average = 0.0 if not durations else sum(durations) / len(durations)
    p95 = _percentile(durations, 0.95)
    return MetricSummary(
        total,
        failures,
        dict(sorted(commands.items())),
        round(average, 3),
        round(p95, 3),
    )


def _json_object(raw: str) -> dict[str, object] | None:
    try:
        loaded = cast(object, json.loads(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return cast(dict[str, object], loaded)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(math.ceil(len(ordered) * fraction) - 1, 0), len(ordered) - 1)
    return ordered[index]


def _rotate(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= MAX_METRICS_BYTES:
        return
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP_ROWS:]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _ = temporary.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _locked(path: Path) -> Generator[None, None, None]:
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
