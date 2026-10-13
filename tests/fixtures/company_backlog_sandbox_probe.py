"""Run inside a disposable user unit; arguments: owned canary, outer user/mount inode."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    canary = Path(sys.argv[1])
    outer_user, outer_mount = int(sys.argv[2]), int(sys.argv[3])
    home_readonly = False
    try:
        _ = canary.write_text("UNEXPECTED_WRITE", encoding="utf-8")
    except OSError as exc:
        home_readonly = exc.errno == errno.EROFS
    state = Path(os.environ["STATE_DIRECTORY"])
    output = state / "latest.json"
    missing = canary.parent / "absent-company.db"
    wrapper = Path(__file__).resolve().parents[2] / "deploy" / "company-backlog-monitor.py"
    run = subprocess.run(
        [sys.executable, "-I", str(wrapper), "--database", str(missing), "--output", str(output)],
        capture_output=True, check=False, timeout=15,
    )
    checks = {
        "user_namespace_changed": Path("/proc/self/ns/user").stat().st_ino != outer_user,
        "mount_namespace_changed": Path("/proc/self/ns/mnt").stat().st_ino != outer_mount,
        "home_write_rejected_erofs": home_readonly,
        "system_mount_readonly": bool(os.statvfs("/usr").f_flag & os.ST_RDONLY),
        "state_result_writable": output.is_file(),
        "wrapper_expected_read_error": run.returncode == 1 and run.stderr == b"",
        "file_matches_stdout": output.is_file() and output.read_bytes() == run.stdout,
        "result_private": output.is_file() and output.stat().st_mode & 0o777 == 0o600,
        "input_not_created": not missing.exists(),
    }
    print(json.dumps(checks, separators=(",", ":")))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
