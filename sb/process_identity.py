"""Conservative local process liveness and Linux boot/start identity checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    state: Literal["alive", "dead", "unknown"]
    identity: str | None = None


def observe_process(process_id: int) -> ProcessObservation:
    if process_id <= 0:
        return ProcessObservation("unknown")
    try:
        status = Path(f"/proc/{process_id}/stat").read_text()
        # The comm field can contain spaces and parentheses. Fields after its
        # final ')' start with field 3 (state); starttime is field 22.
        fields = status.rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X", "x"}:
            return ProcessObservation("dead")
        started = int(fields[19])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if boot:
            return ProcessObservation("alive", f"{boot}:{started}")
    except (OSError, ValueError, IndexError):
        pass
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return ProcessObservation("dead")
    except (PermissionError, OSError):
        return ProcessObservation("unknown")
    return ProcessObservation("alive")
