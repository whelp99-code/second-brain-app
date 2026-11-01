"""Verify installed company runtime stays disabled without external freshness evidence."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tests.test_company_candidate_handoff import ENROLL_KEY, setup_config, signed_request
from tests.test_company_memory_profile import decoded_object


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("executable", type=Path)
    arguments = parser.parse_args()
    executable = cast(Path, arguments.executable).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="sb-company-handoff-smoke-") as directory:
        root = Path(directory)
        config = setup_config(root)
        database = root / "company" / "company.db"
        before = database.read_bytes()
        result = subprocess.run(
            [str(executable), "enroll-handoff", "--config", str(config)],
            input=signed_request("enroll_handoff", {}, ENROLL_KEY, "enroll", at=datetime.now(UTC)),
            capture_output=True,
            check=False,
            timeout=15,
            env={**os.environ},
        )
        assert result.returncode == 2
        assert decoded_object(result.stderr)["error"] == "COMPANY_FRESHNESS_REQUIRED"
        assert before == database.read_bytes()
        print('{"unconfigured_enrollment_denied":true,"database_unchanged":true}')
    assert not root.exists()
    print('{"cleanup":true}')


if __name__ == "__main__":
    main()
