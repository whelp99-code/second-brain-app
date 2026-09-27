"""Shared backup bounds, content digests and read-only runtime metadata."""

import hashlib
import os
import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Final

from sb.redaction import redact_credentials

BACKUP_FORMAT: Final = "second-brain-backup-v1"
MAX_BACKUP_FILES: Final = 100_000
MAX_BACKUP_BYTES: Final = 10 * 1024 * 1024 * 1024
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type ManifestEntries = list[JsonObject]
_SENSITIVE_DETAIL: Final = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]+|"
    + r"(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret)"
    + r"\s*[:=]\s*[^\s,;]+)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def git_value(root: Path, *args: str) -> str | None:
    completed = _git(root, *args)
    return completed.stdout.strip() if completed.returncode == 0 else None


def package_version() -> str:
    try:
        return metadata.version("second-brain")
    except metadata.PackageNotFoundError:
        return "1.0.0"


def safe_detail(value: str | None, *, limit: int = 240) -> str:
    if not value:
        return ""
    redacted = redact_credentials(_SENSITIVE_DETAIL.sub("[REDACTED]", value))
    return redacted if len(redacted) <= limit else redacted[: limit - 1] + "…"
