"""Typed config loader for second-brain.

Loads `config.toml` (search order: $SB_CONFIG, then the app root) and exposes
typed accessors with defaults per the plan todo-1 body. No third-party deps
beyond stdlib `tomllib` (py3.11+).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_VAULT_ROOT = "/Volumes/DevSpace/second-brain"
DEFAULT_PROMPT_VERSION = "v1"
DEFAULT_MODEL_ID = "unknown"
DEFAULT_UNIFIED_DB_DSN = "postgresql://localhost:5433/unified"

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


def _config_search_path() -> Path:
    env_path = os.environ.get("SB_CONFIG")
    if env_path:
        return Path(env_path)
    return APP_ROOT / "config.toml"


def _load_toml(path: Path) -> dict:
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

    raw: dict = field(default_factory=dict, repr=False)

    @property
    def vault_root(self) -> str:
        return self.raw.get("vault_root", DEFAULT_VAULT_ROOT)

    @property
    def caps(self) -> dict[str, int]:
        merged = dict(DEFAULT_CAPS)
        merged.update(self.raw.get("caps", {}))
        return merged

    @property
    def llm(self) -> LlmConfig:
        section = self.raw.get("llm", {})
        return LlmConfig(
            argv_template=list(section.get("argv_template", DEFAULT_ARGV_TEMPLATE)),
            prompt_version=section.get("prompt_version", DEFAULT_PROMPT_VERSION),
            model_id=section.get("model_id", DEFAULT_MODEL_ID),
        )

    @property
    def unified_db(self) -> UnifiedDbConfig:
        section = self.raw.get("unified_db", {})
        return UnifiedDbConfig(dsn=section.get("dsn", DEFAULT_UNIFIED_DB_DSN))

    @property
    def source_roots(self) -> list[dict]:
        return list(self.raw.get("sources", []))


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml from `path`, else $SB_CONFIG, else the app root.

    Missing file => empty raw dict, all accessors fall back to defaults.
    """
    resolved = Path(path) if path is not None else _config_search_path()
    return Config(raw=_load_toml(resolved))
