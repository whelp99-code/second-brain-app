"""Typed config loader for second-brain.

Loads `config.toml` (search order: $SB_CONFIG, user config, then the app root) and exposes
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

DEFAULT_PROMPT_VERSION = "v1"
DEFAULT_MODEL_ID = "unknown"
DEFAULT_UNIFIED_DB_DSN = "postgresql://localhost:5433/unified"
FILESYSTEM_MODES = frozenset({"strict", "trusted-root", "audit-only"})

DEFAULT_CAPS: dict[str, int] = {
    "max_llm_calls_compile": 200,
    "max_llm_calls_conflict": 200,
    "max_llm_calls_briefing": 10,
    "max_new_units_per_run": 500,
    "max_db_rows_per_run": 5000,
    "max_derivation_attempts": 3,
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


def _as_bool(value: TomlValue | None) -> bool | None:
    return value if isinstance(value, bool) else None


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


def _xdg_config_home() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".config"


def _xdg_data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".local" / "share"


def user_config_path() -> Path:
    return _xdg_config_home() / "second-brain" / "config.toml"


def default_vault_root() -> Path:
    return _xdg_data_home() / "second-brain" / "vault"


def default_knowledge_registry_path() -> Path:
    return _xdg_data_home() / "second-brain" / "knowledge-registry.sqlite"


DEFAULT_VAULT_ROOT = str(default_vault_root())


def _config_search_path() -> Path:
    env_path = os.environ.get("SB_CONFIG")
    if env_path:
        return Path(os.path.expandvars(env_path)).expanduser()
    user_path = user_config_path()
    if user_path.is_file():
        return user_path
    app_path = APP_ROOT / "config.toml"
    return app_path if app_path.is_file() else user_path


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
class FilesystemConfig:
    mode: str = "trusted-root"


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: int = 1
    max_delay_seconds: int = 60


@dataclass(frozen=True, slots=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    token: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    allow_external_llm: bool = False
    redact_pii: bool = False


@dataclass(frozen=True, slots=True)
class Config:
    """Typed, immutable view over config.toml + defaults."""

    raw: Mapping[str, TomlValue] = field(default_factory=_empty_raw, repr=False)
    base_dir: Path = field(default_factory=Path.cwd, repr=False)

    def _path(self, value: str | None, default: Path) -> str:
        raw = str(default) if value is None else value
        expanded = Path(os.path.expandvars(raw)).expanduser()
        resolved = expanded if expanded.is_absolute() else self.base_dir / expanded
        return str(resolved.resolve(strict=False))

    @property
    def vault_root(self) -> str:
        text = _as_str(self.raw.get("vault_root"))
        return self._path(text, default_vault_root())

    @property
    def knowledge_registry(self) -> str:
        text = _as_str(self.raw.get("knowledge_registry"))
        return self._path(text, default_knowledge_registry_path())

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
        roots = _as_source_roots(self.raw.get("sources"))
        normalized: list[dict[str, str]] = []
        for item in roots:
            copied = dict(item)
            root = copied.get("root")
            if root:
                copied["root"] = self._path(root, self.base_dir)
            normalized.append(copied)
        return normalized

    @property
    def configured_source_ids(self) -> tuple[str, ...] | None:
        """Return the explicit source selection shared by CLI, web, and MCP runs."""
        names: list[str] = []
        for row in self.source_roots:
            selected = row.get("id") or row.get("adapter") or row.get("type")
            if selected and selected not in names:
                names.append(selected)
        return tuple(names) or None

    @property
    def filesystem(self) -> FilesystemConfig:
        section = _as_mapping(self.raw.get("filesystem"))
        mode = None if section is None else _as_str(section.get("mode"))
        selected = mode if mode in FILESYSTEM_MODES else "trusted-root"
        return FilesystemConfig(selected)

    @property
    def retry(self) -> RetryConfig:
        section = _as_mapping(self.raw.get("retry"))
        if section is None:
            return RetryConfig(max_attempts=self.caps["max_derivation_attempts"])
        attempts = _as_int(section.get("max_attempts"))
        base = _as_int(section.get("base_delay_seconds"))
        maximum = _as_int(section.get("max_delay_seconds"))
        return RetryConfig(
            max_attempts=max(1, attempts or self.caps["max_derivation_attempts"]),
            base_delay_seconds=max(0, base if base is not None else 1),
            max_delay_seconds=max(0, maximum if maximum is not None else 60),
        )

    @property
    def web(self) -> WebConfig:
        section = _as_mapping(self.raw.get("web"))
        if section is None:
            return WebConfig()
        host = _as_str(section.get("host")) or "127.0.0.1"
        port = _as_int(section.get("port")) or 8765
        token = _as_str(section.get("token"))
        return WebConfig(host, port, token)

    @property
    def security(self) -> SecurityConfig:
        section = _as_mapping(self.raw.get("security"))
        if section is None:
            return SecurityConfig()
        external = _as_bool(section.get("allow_external_llm"))
        pii = _as_bool(section.get("redact_pii"))
        return SecurityConfig(bool(external), bool(pii))


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml from `path`, else $SB_CONFIG, else the app root.

    Missing file => empty raw dict, all accessors fall back to defaults.
    """
    resolved = Path(path).expanduser() if path is not None else _config_search_path()
    resolved = resolved.resolve(strict=False)
    return Config(raw=_load_toml(resolved), base_dir=resolved.parent)
