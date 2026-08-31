from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from sb.cli import main


def test_maintenance_oneshot_is_a_real_provider_entrypoint() -> None:
    # Given: the provider CLI command inventory.
    output = StringIO()

    # When: CLI help is rendered.
    with redirect_stdout(output):
        code = main(["--help"])

    # Then: deterministic lifecycle maintenance is independently runnable.
    assert code == 0
    assert "maintain" in output.getvalue()
