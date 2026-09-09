"""Explicit provider runtime wiring shared by CLI and future admission surfaces."""
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sb.config import Config
from sb.scoped_provider_decision import create_scoped_provider_authority
from sb.scoped_provider_https import (
    create_scoped_provider_https,
    validate_scoped_provider_https_config,
)
from sb.scoped_write_request import ScopedWriteRequest


def configured_scoped_provider_authority(config: Config) -> Callable[[ScopedWriteRequest], bool] | None:
    """Absent configuration preserves legacy execution. Malformed never disables checks.

    A fixed absolute credential path is server configuration, not request input.
    Its current credential bytes and the gateway session/policy are re-read for
    every check. No credential, session, grant or policy file is created here.
    """
    if "scoped_provider_verifier" not in config.raw:
        return None
    section = config.raw["scoped_provider_verifier"]
    if not isinstance(section, dict) or set(section) != {"credentials_path"}:
        raise ValueError("SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID")
    path = section["credentials_path"]
    if (not isinstance(path, str) or not path or not Path(path).is_absolute()
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError("SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID")
    try:
        validate_scoped_provider_https_config(Path(path))
    except (OSError, ValueError) as exc:
        raise ValueError("SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID") from exc
    channel = create_scoped_provider_https(Path(path))
    return create_scoped_provider_authority(channel, clock=lambda: datetime.now(UTC))
