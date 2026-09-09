"""Read-only systemd unit drain gate; never stops, masks or restarts services.

This checks the named unit boundary only. It does not prove absence of manual
processes, open database descriptors, remote clients, or future reactivation.
"""

from __future__ import annotations

import json
import subprocess

UNITS = (
    "jm-jarvis.service",
    "jm-jarvis-dashboard.service",
    "jm-jarvis-phone-gateway.service",
    "jm-jarvis-backup.timer",
    "jm-jarvis-backup.service",
    "jm-jarvis-portfolio-collector.timer",
    "jm-jarvis-portfolio-collector.service",
    "jm-second-brain-refresh.timer",
    "jm-second-brain-refresh.service",
    "jm-second-brain-maintenance.timer",
    "jm-second-brain-maintenance.service",
    "jm-second-brain-requests.path",
    "jm-second-brain-requests.service",
    "second-brain-web.service",
    "second-brain.timer",
    "second-brain.service",
    "second-brain-backup.timer",
    "second-brain-backup.service",
)
PROPERTIES = ("LoadState", "ActiveState", "SubState", "MainPID", "ControlPID", "Job")


def assess_unit(values: dict[str, str]) -> list[str]:
    reasons = []
    if values.get("LoadState") != "loaded":
        reasons.append("UNIT_NOT_LOADED")
    if values.get("ActiveState") != "inactive" or values.get("SubState") != "dead":
        reasons.append("UNIT_NOT_DRAINED")
    for name in ("MainPID", "ControlPID"):
        if values.get(name, "0") != "0":
            reasons.append("UNIT_HAS_PROCESS")
            break
    if values.get("Job", ""):
        reasons.append("UNIT_HAS_PENDING_JOB")
    return reasons


def main() -> int:
    results = []
    for unit in UNITS:
        response = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=" + ",".join(PROPERTIES)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        values = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
        reasons = assess_unit(values) if response.returncode == 0 else ["UNIT_QUERY_FAILED"]
        results.append({"unit": unit, "state": values, "hold_reasons": reasons})
    ready = not any(row["hold_reasons"] for row in results)
    print(
        json.dumps(
            {
                "named_units_drained": ready,
                "units": results,
                "scope": "read-only named systemd units; not a complete process or activation gate",
                "production_activation_authorized": False,
            },
            indent=2,
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
