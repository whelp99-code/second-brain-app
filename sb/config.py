"""Typed config loader for second-brain.

Loads `config.toml` (search order: $SB_CONFIG, then the app root) and exposes
typed accessors with defaults per the plan todo-1 body. No third-party deps
beyond stdlib `tomllib` (py3.11+).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VAULT_ROOT = "/Volumes/DevSpace/second-brain"
DEFAULT_PROMPT_VERSION = "v1"
DEFAULT_MODEL_ID = "unknown"
DEFAULT_UNIFIED_DB_DSN = "postgresql://localhost:5433/unified"
DEFAULT_REQUEST_ROOT = "/home/jm/.local/state/second-brain/requests"
DEFAULT_EXPORT_ROOT = "/home/jm/.local/state/second-brain/exports"
DEFAULT_ACTIVE_VAULT = "/home/jm/.local/share/second-brain/vault"
DEFAULT_GENERATION_ROOT = "/home/jm/.local/share/second-brain/vault-generations"
DEFAULT_STATE_ROOT = "/home/jm/.local/state/second-brain"
DEFAULT_BACKUP_ROOT = "/home/jm/.local/state/second-brain/backups"
DEFAULT_PROVIDER_INSTANCE_ID = "provider:second-brain:linux"

DEFAULT_CAPS: dict[str, int] = {
    "max_llm_calls_compile": 200,
    "max_llm_calls_conflict": 200,
    "max_llm_calls_briefing": 10,
    "max_new_units_per_run": 500,
    "max_db_rows_per_run": 5000,
}

# Adjustment point A: exact non-interactive LLM CLI invocation is probed and
# recorded per-deployment in config.toml under [llm] argv_template. This is
# a placeholder until a real vault config (todo 17) records the probed value.
DEFAULT_ARGV_TEMPLATE: list[str] = ["claude", "-p", "{prompt}"]

type TomlValue = (
    str | int | float | bool | date | datetime | time | list[TomlValue] | Mapping[str, TomlValue]
)


def _empty_raw() -> dict[str, TomlValue]:
    return {}


def _as_str(value: TomlValue | None) -> str | None:
    match value:
        case str() as text:
            return text
        case int() | float() | date() | time() | list() | Mapping() | None:
            return None


def _as_int(value: TomlValue | None) -> int | None:
    match value:
        case bool():
            return None
        case int() as count:
            return count
        case str() | float() | date() | time() | list() | Mapping() | None:
            return None


def _as_mapping(value: TomlValue | None) -> Mapping[str, TomlValue] | None:
    match value:
        case Mapping() as mapping:
            return mapping
        case str() | int() | float() | date() | time() | list() | None:
            return None


def _as_str_list(value: TomlValue | None) -> list[str] | None:
    match value:
        case list() as items:
            texts: list[str] = []
            for item in items:
                text = _as_str(item)
                if text is None:
                    return None
                texts.append(text)
            return texts
        case str() | int() | float() | date() | time() | Mapping() | None:
            return None


def _as_str_mapping(value: TomlValue | None) -> dict[str, str]:
    mapping = _as_mapping(value)
    if mapping is None:
        return {}
    result: dict[str, str] = {}
    for key, item in mapping.items():
        parsed = _as_str(item)
        if parsed is None:
            return {}
        result[key] = parsed
    return result


def _as_source_roots(value: TomlValue | None) -> list[dict[str, str]]:
    match value:
        case list() as items:
            roots: list[dict[str, str]] = []
            for item in items:
                mapping = _as_mapping(item)
                if mapping is None:
                    return []
                root: dict[str, str] = {}
                for key, inner in mapping.items():
                    text = _as_str(inner)
                    if text is None:
                        return []
                    root[key] = text
                roots.append(root)
            return roots
        case str() | int() | float() | date() | time() | Mapping() | None:
            return []


def _config_search_path() -> Path:
    env_path = os.environ.get("SB_CONFIG")
    if env_path:
        return Path(env_path)
    return APP_ROOT / "config.toml"


def _load_toml(path: Path) -> Mapping[str, TomlValue]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


@dataclass(frozen=True, slots=True)
class UnifiedDbConfig:
    dsn: str = DEFAULT_UNIFIED_DB_DSN


@dataclass(frozen=True, slots=True)
class LlmConfig:
    argv_template: list[str] = field(default_factory=lambda: list(DEFAULT_ARGV_TEMPLATE))
    prompt_version: str = DEFAULT_PROMPT_VERSION
    model_id: str = DEFAULT_MODEL_ID


@dataclass(frozen=True, slots=True)
class Config:
    """Typed, immutable view over config.toml + defaults."""

    raw: Mapping[str, TomlValue] = field(default_factory=_empty_raw, repr=False)

    @property
    def vault_root(self) -> str:
        text = _as_str(self.raw.get("vault_root"))
        return DEFAULT_VAULT_ROOT if text is None else text

    @property
    def request_root(self) -> str:
        text = _as_str(self.raw.get("request_root"))
        return DEFAULT_REQUEST_ROOT if text is None else text

    @property
    def export_root(self) -> str:
        text = _as_str(self.raw.get("export_root"))
        return DEFAULT_EXPORT_ROOT if text is None else text

    @property
    def state_root(self) -> str:
        text = _as_str(self.raw.get("state_root"))
        return DEFAULT_STATE_ROOT if text is None else text

    @property
    def share_root(self) -> str:
        text = _as_str(self.raw.get("share_root"))
        if text is not None:
            return text
        return str(Path(DEFAULT_ACTIVE_VAULT).parent)

    @property
    def generation_root(self) -> str:
        text = _as_str(self.raw.get("generation_root"))
        return DEFAULT_GENERATION_ROOT if text is None else text

    @property
    def backup_root(self) -> str:
        text = _as_str(self.raw.get("backup_root"))
        return DEFAULT_BACKUP_ROOT if text is None else text

    @property
    def provider_instance_id(self) -> str:
        text = _as_str(self.raw.get("provider_instance_id"))
        return DEFAULT_PROVIDER_INSTANCE_ID if text is None else text

    @property
    def provider_release_sha(self) -> str:
        text = _as_str(self.raw.get("provider_release_sha"))
        return "development" if text is None else text

    @property
    def jarvis_signing_key_id(self) -> str | None:
        return _as_str(self.raw.get("jarvis_signing_key_id"))

    @property
    def jarvis_public_key(self) -> str | None:
        return _as_str(self.raw.get("jarvis_public_key"))

    @property
    def jarvis_public_keys(self) -> dict[str, str]:
        keys = _as_str_mapping(self.raw.get("jarvis_public_keys"))
        key_id = self.jarvis_signing_key_id
        key = self.jarvis_public_key
        if key_id is not None and key is not None:
            _ = keys.setdefault(key_id, key)
        return keys

    @property
    def revoked_jarvis_signing_key_ids(self) -> frozenset[str]:
        return frozenset(_as_str_list(self.raw.get("revoked_jarvis_signing_key_ids")) or [])

    @property
    def revoked_delegation_ids(self) -> frozenset[str]:
        return frozenset(_as_str_list(self.raw.get("revoked_delegation_ids")) or [])

    @property
    def external_erasure_public_keys(self) -> dict[str, str]:
        return _as_str_mapping(self.raw.get("external_erasure_public_keys"))

    @property
    def provider_signing_key_id(self) -> str | None:
        return _as_str(self.raw.get("provider_signing_key_id"))

    @property
    def provider_private_key(self) -> str | None:
        return _as_str(self.raw.get("provider_private_key"))

    @property
    def caps(self) -> dict[str, int]:
        merged = dict(DEFAULT_CAPS)
        section = _as_mapping(self.raw.get("caps"))
        if section is None:
            return merged
        for key, value in section.items():
            parsed = _as_int(value)
            if parsed is not None:
                merged[key] = parsed
        return merged

    @property
    def llm(self) -> LlmConfig:
        section = _as_mapping(self.raw.get("llm"))
        if section is None:
            return LlmConfig()
        argv_template = _as_str_list(section.get("argv_template"))
        prompt_version = _as_str(section.get("prompt_version"))
        model_id = _as_str(section.get("model_id"))
        return LlmConfig(
            argv_template=list(DEFAULT_ARGV_TEMPLATE if argv_template is None else argv_template),
            prompt_version=DEFAULT_PROMPT_VERSION if prompt_version is None else prompt_version,
            model_id=DEFAULT_MODEL_ID if model_id is None else model_id,
        )

    @property
    def unified_db(self) -> UnifiedDbConfig:
        section = _as_mapping(self.raw.get("unified_db"))
        if section is None:
            return UnifiedDbConfig()
        dsn = _as_str(section.get("dsn"))
        return UnifiedDbConfig(dsn=DEFAULT_UNIFIED_DB_DSN if dsn is None else dsn)

    @property
    def source_roots(self) -> list[dict[str, str]]:
        return _as_source_roots(self.raw.get("sources"))


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml from `path`, else $SB_CONFIG, else the app root.

    Missing file => empty raw dict, all accessors fall back to defaults.
    """
    resolved = Path(path) if path is not None else _config_search_path()
    return Config(raw=_load_toml(resolved))
