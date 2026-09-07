from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from sb.cli import main


def test_apply_requests_help_exposes_explicit_test_control_socket() -> None:
    # Given: the real provider apply CLI boundary.
    output = StringIO()

    # When: its machine-consumed test harness option is requested through help.
    with redirect_stdout(output):
        code = main(["apply-requests", "--help"])

    # Then: an explicit socket option exists without changing production argv.
    assert code == 0
    assert "--test-control-socket" in output.getvalue()
