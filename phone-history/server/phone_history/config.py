"""Runtime configuration for the Phone History service."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from phone_history.errors import ConfigurationError

_DEFAULT_MAX_REQUEST_BYTES = 15 * 1024 * 1024
_DEFAULT_ATTACHMENT_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings.

    Secrets are injected at runtime and are never serialized by this object.
    """

    data_dir: Path
    api_token: str
    master_key: bytes
    second_brain_vault: Path | None = None
    second_brain_base_url: str | None = None
    second_brain_token_env: str = "SB_WEB_TOKEN"
    host: str = "127.0.0.1"
    port: int = 8787
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES
    attachment_retention_days: int = _DEFAULT_ATTACHMENT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if len(self.api_token) < 32:
            raise ConfigurationError("PHONE_HISTORY_API_TOKEN must contain at least 32 characters")
        if len(self.master_key) != 32:
            raise ConfigurationError("PHONE_HISTORY_MASTER_KEY_B64 must decode to 32 bytes")
        if not (0 < self.port < 65536):
            raise ConfigurationError("PHONE_HISTORY_PORT is invalid")
        if self.max_request_bytes < 1024:
            raise ConfigurationError("PHONE_HISTORY_MAX_REQUEST_BYTES is too small")
        if not (1 <= self.attachment_retention_days <= 3650):
            raise ConfigurationError("attachment retention must be between 1 and 3650 days")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "phone-history.sqlite3"

    @property
    def attachment_dir(self) -> Path:
        return self.data_dir / "attachments"

    @classmethod
    def from_environment(cls) -> Settings:
        data_dir = Path(os.environ.get("PHONE_HISTORY_DATA_DIR", "~/.local/share/phone-history"))
        token = os.environ.get("PHONE_HISTORY_API_TOKEN", "")
        encoded_key = os.environ.get("PHONE_HISTORY_MASTER_KEY_B64", "")
        if not token:
            raise ConfigurationError("PHONE_HISTORY_API_TOKEN is required")
        if not encoded_key:
            raise ConfigurationError("PHONE_HISTORY_MASTER_KEY_B64 is required")
        key = _decode_key(encoded_key)
        raw_vault = os.environ.get("PHONE_HISTORY_SECOND_BRAIN_VAULT", "").strip()
        vault = Path(raw_vault).expanduser() if raw_vault else None
        raw_base = os.environ.get("PHONE_HISTORY_SECOND_BRAIN_BASE_URL", "").strip()
        token_env = os.environ.get("PHONE_HISTORY_SECOND_BRAIN_TOKEN_ENV", "SB_WEB_TOKEN").strip()
        if not token_env:
            token_env = "SB_WEB_TOKEN"
        try:
            port = int(os.environ.get("PHONE_HISTORY_PORT", "8787"))
            maximum = int(
                os.environ.get("PHONE_HISTORY_MAX_REQUEST_BYTES", str(_DEFAULT_MAX_REQUEST_BYTES))
            )
            retention = int(
                os.environ.get(
                    "PHONE_HISTORY_ATTACHMENT_RETENTION_DAYS",
                    str(_DEFAULT_ATTACHMENT_RETENTION_DAYS),
                )
            )
        except ValueError as exc:
            raise ConfigurationError("numeric Phone History setting is invalid") from exc
        return cls(
            data_dir=data_dir.expanduser(),
            api_token=token,
            master_key=key,
            second_brain_vault=vault,
            second_brain_base_url=raw_base or None,
            second_brain_token_env=token_env,
            host=os.environ.get("PHONE_HISTORY_HOST", "127.0.0.1"),
            port=port,
            max_request_bytes=maximum,
            attachment_retention_days=retention,
        )

    def prepare(self) -> None:
        """Create private runtime directories without exposing secret values."""
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.attachment_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.data_dir.chmod(0o700)
            self.attachment_dir.chmod(0o700)
        except OSError:
            # Permission hardening is verified separately; non-POSIX test filesystems may ignore it.
            pass


def _decode_key(value: str) -> bytes:
    normalized = value.strip()
    padding = "=" * (-len(normalized) % 4)
    try:
        return base64.urlsafe_b64decode(normalized + padding)
    except (ValueError, base64.binascii.Error) as exc:
        raise ConfigurationError("PHONE_HISTORY_MASTER_KEY_B64 is not valid base64") from exc
