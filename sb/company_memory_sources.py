"""Resolve company-only source bytes from an operator-pinned local profile."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field

from sb.company_memory import CompanyMemoryError
from sb.effect_values import JsonObject
from sb.effect_write_models import ClosedModel

_MAX_SOURCE_BYTES = 1_048_576


class CompanySourceBinding(ClosedModel):
    path: str
    source_system: str
    source_event_id: str
    parser_version: str
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CompanySourceProfile(ClosedModel):
    schema_version: Literal[1]
    source_roots: list[str]
    bindings: dict[str, CompanySourceBinding]


def resolve_company_source(
    profile: CompanySourceProfile,
    arguments: JsonObject,
    personal_roots: list[str],
) -> str:
    """Resolve only the exact signed reference beneath permitted company roots."""
    locator = arguments.get("source_locator")
    if not isinstance(locator, str) or locator not in profile.bindings:
        raise CompanyMemoryError("COMPANY_SOURCE_BINDING_REQUIRED")
    binding = profile.bindings[locator]
    expected = {
        "source_system": binding.source_system,
        "source_event_id": binding.source_event_id,
        "parser_version": binding.parser_version,
        "content_digest": binding.content_digest,
    }
    for field, value in expected.items():
        if arguments.get(field) != value:
            raise CompanyMemoryError("COMPANY_SOURCE_BINDING_MISMATCH")
    path = Path(binding.path)
    roots = [Path(value) for value in profile.source_roots]
    if not path.is_absolute() or not roots or any(not root.is_absolute() for root in roots):
        raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
    resolved = path.resolve(strict=False)
    if (
        path.is_symlink()
        or not any(resolved.is_relative_to(root.resolve(strict=False)) for root in roots)
        or any(resolved.is_relative_to(Path(root).resolve(strict=False)) for root in personal_roots)
        or not resolved.is_file()
    ):
        raise CompanyMemoryError("COMPANY_SOURCE_SCOPE_DENIED")
    try:
        with resolved.open("rb") as source:
            content = source.read(_MAX_SOURCE_BYTES + 1)
        if len(content) > _MAX_SOURCE_BYTES:
            raise CompanyMemoryError("COMPANY_SOURCE_TOO_LARGE")
        if "sha256:" + hashlib.sha256(content).hexdigest() != binding.content_digest:
            raise CompanyMemoryError("COMPANY_SOURCE_BINDING_MISMATCH")
        return content.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CompanyMemoryError("COMPANY_SOURCE_UNAVAILABLE") from exc
