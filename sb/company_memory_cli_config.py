"""Trusted configuration shared by the bounded company CLI routes."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from sb.company_approver_binding import CompanyHandoffPolicy
from sb.company_freshness import FreshnessProviderConfig
from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import CompanyKeyScope
from sb.company_memory_sources import CompanySourceProfile
from sb.effect_values import CanonicalValueError, strict_loads
from sb.effect_write_models import ClosedModel

MAX_COMPANY_CONFIG = 65_536


class CompanyCliConfigV1(ClosedModel):
    schema_version: Literal[1]
    company_database: str
    personal_data_roots: list[str]
    provider_instance_id: str
    workspace_id: str
    principal_id: str
    agent_id: str
    session_id: str
    projects: list[str]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str
    trusted_keys: dict[str, str]
    source_profile: CompanySourceProfile | None = None
    key_scopes: dict[str, CompanyKeyScope] = Field(default_factory=dict)
    handoff_policy: CompanyHandoffPolicy | None = None
    freshness_provider: FreshnessProviderConfig = Field(
        default_factory=lambda: FreshnessProviderConfig(schema_version=2, kind="unconfigured"),
    )


def load_company_config(path: Path) -> CompanyCliConfigV1:
    try:
        value = strict_loads(path.read_bytes(), MAX_COMPANY_CONFIG)
        if not isinstance(value, dict):
            raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
        config = CompanyCliConfigV1.model_validate(value)
        if not config.key_scopes.keys() <= config.trusted_keys.keys():
            raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
        return config
    except (OSError, ValueError, ValidationError, CanonicalValueError) as exc:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID") from exc


def company_database_path(config: CompanyCliConfigV1) -> Path:
    database = Path(config.company_database)
    roots = [Path(value) for value in config.personal_data_roots]
    if not database.is_absolute() or not roots or any(not root.is_absolute() for root in roots):
        raise CompanyMemoryError("COMPANY_DATABASE_ISOLATION_REQUIRED")
    resolved_database = database.resolve(strict=False)
    if database.is_symlink() or any(
        resolved_database == root.resolve(strict=False)
        or resolved_database.is_relative_to(root.resolve(strict=False))
        for root in roots
    ):
        raise CompanyMemoryError("COMPANY_DATABASE_ISOLATION_REQUIRED")
    if not resolved_database.parent.is_dir():
        raise CompanyMemoryError("COMPANY_DATABASE_PARENT_REQUIRED")
    return resolved_database


def company_trusted_keys(values: dict[str, str]) -> dict[str, Ed25519PublicKey]:
    result: dict[str, Ed25519PublicKey] = {}
    try:
        for key_id, encoded in values.items():
            if not key_id or len(encoded) != 43 or "=" in encoded:
                raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
            raw = base64.urlsafe_b64decode(encoded + "=")
            if len(raw) != 32:
                raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
            result[key_id] = Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError) as exc:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID") from exc
    if not result:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
    return result
