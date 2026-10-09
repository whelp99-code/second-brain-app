"""Mail-only original registration; no candidate or confirmation writes."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from sb.company_memory import CompanyMemoryError
from sb.company_memory_sources import CompanySourceBinding, CompanySourceProfile
from sb.effect_values import JsonObject, canonical_bytes, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class RegistrationArguments(ClosedModel):
    candidate_id: str = Field(min_length=1)
    source_system: Literal["mail"]
    source_locator: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    locator: JsonObject


@contextmanager
def registration_lock(config_path: Path) -> Generator[None, None, None]:
    """Lock the stable config directory, not the replaced config inode."""
    if config_path.is_symlink():
        raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
    try:
        descriptor = os.open(config_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CompanyMemoryError("COMPANY_SOURCE_REGISTRATION_FAILED") from exc


def _publish(path: Path, raw: bytes, *, replace: bool = True) -> None:
    """Publish flushed bytes atomically; originals use a no-overwrite hard link."""
    descriptor, name = tempfile.mkstemp(prefix=".register-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            _ = output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def register_original(
    config_path: Path,
    document: JsonObject,
    database: Path,
    profile: CompanySourceProfile | None,
    arguments: JsonObject,
    content: str,
    config_maximum: int,
    personal_roots: list[str],
) -> JsonObject:
    """Append one authenticated binding after its retained original is durable."""
    try:
        source = RegistrationArguments.model_validate(arguments)
        raw = content.encode("utf-8")
    except (ValidationError, UnicodeEncodeError) as exc:
        raise CompanyMemoryError("COMPANY_REQUEST_INVALID") from exc
    if len(raw) > 1_048_576:
        raise CompanyMemoryError("COMPANY_SOURCE_TOO_LARGE")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != source.content_digest:
        raise CompanyMemoryError("COMPANY_SOURCE_BINDING_MISMATCH")
    root = database.parent / "sources"
    if root.is_symlink() or any(
        root.resolve(strict=False).is_relative_to(Path(value).resolve(strict=False))
        for value in personal_roots
    ):
        raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
    path = root / f"{digest.removeprefix('sha256:')}.txt"
    binding = CompanySourceBinding(
        path=str(path),
        source_system=source.source_system,
        source_event_id=source.source_event_id,
        parser_version=source.parser_version,
        content_digest=digest,
    )
    existing = profile.bindings.get(source.source_locator) if profile is not None else None
    if existing is not None and existing != binding:
        raise CompanyMemoryError("COMPANY_SOURCE_BINDING_CONFLICT")
    roots = list(profile.source_roots) if profile is not None else []
    if str(root) not in roots:
        roots.append(str(root))
    bindings = dict(profile.bindings) if profile is not None else {}
    bindings[source.source_locator] = binding
    updated = CompanySourceProfile(schema_version=1, source_roots=roots, bindings=bindings)
    serialized = canonical_bytes({**document, "source_profile": model_object(updated)})
    _ = strict_loads(serialized, config_maximum)
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        root_stat = root.lstat()
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.getuid()
            or stat.S_IMODE(root_stat.st_mode) != 0o700
        ):
            raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
        if path.is_symlink():
            raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
        if path.exists():
            path_stat = path.lstat()
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_uid != os.getuid()
                or stat.S_IMODE(path_stat.st_mode) != 0o600
            ):
                raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
            if path.read_bytes() != raw:
                raise CompanyMemoryError("COMPANY_SOURCE_BINDING_MISMATCH")
        else:
            _publish(path, raw, replace=False)
        if existing is None:
            _publish(config_path, serialized)
    except OSError as exc:
        raise CompanyMemoryError("COMPANY_SOURCE_REGISTRATION_FAILED") from exc
    return {
        "registration": {
            "state": "registered",
            "source_locator": source.source_locator,
            "content_digest": digest,
        },
    }
