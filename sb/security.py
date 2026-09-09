"""Source-scoped LLM egress and prompt-time sensitive-data policy."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Final, cast

from sb.config import Config
from sb.contracts import BriefingInputs, Unit

_EMAIL: Final = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_BEARER: Final = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRET_ASSIGN: Final = re.compile(
    r"(?im)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b"
    + r"\s*[:=]\s*([^\s,;]{4,})"
)
_PRIVATE_KEY: Final = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_ORIGIN: Final = re.compile(r"(?:^|\s)origin=([^:\s]+):")
_LOCAL_MODEL_PREFIXES: Final = ("local:", "ollama:", "llamacpp:", "lmstudio:")
_LOCAL_COMMANDS: Final = frozenset({"ollama", "llama-server", "llamacpp", "lmstudio"})
_VALID_LLM_POLICIES: Final = frozenset({"allow", "deny", "local-only"})
_VALID_SENSITIVE_POLICIES: Final = frozenset({"mask", "allow", "deny"})


class SecurityPolicyError(RuntimeError):
    """Raised when configured data-egress policy refuses an LLM prompt."""

    source_id: str
    reason: str

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"source {source_id}: {reason}")


def mask_sensitive(text: str) -> str:
    """Mask common secrets and personal identifiers in an LLM-bound copy."""
    # Each literal is required by its regex. Check the current intermediate
    # string so overlapping replacements retain the original policy order.
    protected = text
    if "-----BEGIN " in protected:
        protected = _PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", protected)
    protected = _BEARER.sub("Bearer [REDACTED_TOKEN]", protected)
    if ":" in protected or "=" in protected:
        protected = _SECRET_ASSIGN.sub(
            lambda match: f"{match.group(1)}=[REDACTED_SECRET]",
            protected,
        )
    if "@" in protected:
        protected = _EMAIL.sub("[REDACTED_EMAIL]", protected)
    return protected


def llm_is_external(config: Config) -> bool:
    """Return whether the configured model transports prompts outside this host."""
    raw_llm = _mapping(config.raw.get("llm"))
    explicit = raw_llm.get("external")
    if isinstance(explicit, bool):
        return explicit
    model = config.llm.model_id.casefold()
    if model in {"fake", "test", "unknown"} or model.startswith(_LOCAL_MODEL_PREFIXES):
        return False
    argv = config.llm.argv_template
    command = _command_name(argv[0]).casefold() if argv else ""
    return command not in _LOCAL_COMMANDS


def _command_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def protect_unit(unit: Unit, config: Config) -> Unit:
    """Apply source egress and sensitive-data policy to one prompt-bound unit."""
    source_id = unit.origin.partition(":")[0] or "unknown"
    policy, sensitive = _policies(config, source_id)
    _enforce_egress(source_id, policy, config)
    protected = mask_sensitive(unit.text)
    if sensitive == "deny" and protected != unit.text:
        raise SecurityPolicyError(source_id, "sensitive content denied")
    if sensitive == "allow":
        return unit
    return replace(unit, text=protected)


def protect_units(units: list[Unit], config: Config) -> list[Unit]:
    """Return prompt-safe copies while preserving immutable source objects."""
    return [protect_unit(unit, config) for unit in units]


def protect_briefing_inputs(inputs: BriefingInputs, config: Config) -> BriefingInputs:
    """Apply source policy and masking to all text that can enter briefing prompts."""
    return BriefingInputs(
        tuple(_protect_line(line, config) for line in inputs.yesterday_items),
        tuple(mask_sensitive(line) for line in inputs.open_conflict_pages),
        tuple(_protect_line(line, config) for line in inputs.stale_pages),
        tuple(_protect_line(line, config) for line in inputs.upcoming_items),
        None if inputs.last_brief is None else mask_sensitive(inputs.last_brief),
        inputs.previous_run_status,
    )


def source_policy_snapshot(config: Config) -> tuple[dict[str, object], ...]:
    """Return a redaction-safe operator view of configured source policies."""
    rows: list[dict[str, object]] = []
    raw_sources = config.raw.get("sources")
    if not isinstance(raw_sources, list):
        return ()
    for item in cast(list[object], raw_sources):
        row = _mapping(item)
        source_id = _text(row.get("id")) or ""
        adapter = _text(row.get("adapter")) or _text(row.get("type")) or ""
        raw_root = _text(row.get("root"))
        root = None if raw_root is None else config.resolve_path(raw_root)
        llm_policy, sensitive = _policies(config, source_id)
        rows.append(
            {
                "id": source_id,
                "adapter": adapter,
                "root": root,
                "root_exists": None if root is None else _expanded_exists(root),
                "llm_policy": llm_policy,
                "sensitive": sensitive,
                "external_model": llm_is_external(config),
            }
        )
    rows.sort(key=lambda row: (str(row["id"]), str(row["adapter"])))
    return tuple(rows)


def _protect_line(line: str, config: Config) -> str:
    matched = _ORIGIN.search(line)
    if matched is not None:
        source_id = matched.group(1)
        policy, sensitive = _policies(config, source_id)
        _enforce_egress(source_id, policy, config)
        protected = mask_sensitive(line)
        if sensitive == "deny" and protected != line:
            raise SecurityPolicyError(source_id, "sensitive content denied")
        return line if sensitive == "allow" else protected
    return mask_sensitive(line)


def _enforce_egress(source_id: str, policy: str, config: Config) -> None:
    external = llm_is_external(config)
    if policy == "deny":
        raise SecurityPolicyError(source_id, "LLM egress denied by source policy")
    if policy == "local-only" and external:
        raise SecurityPolicyError(source_id, "source is restricted to a local model")


def _policies(config: Config, source_id: str) -> tuple[str, str]:
    row = _source_row(config, source_id)
    default_llm = "deny" if llm_is_external(config) else "allow"
    policy = _text(row.get("llm_policy")) or default_llm
    sensitive = _text(row.get("sensitive")) or "mask"
    if policy not in _VALID_LLM_POLICIES:
        raise SecurityPolicyError(source_id, f"invalid llm_policy {policy!r}")
    if sensitive not in _VALID_SENSITIVE_POLICIES:
        raise SecurityPolicyError(source_id, f"invalid sensitive policy {sensitive!r}")
    return policy, sensitive


def _source_row(config: Config, source_id: str) -> Mapping[str, object]:
    raw_sources = config.raw.get("sources")
    if not isinstance(raw_sources, list):
        return {}
    for item in cast(list[object], raw_sources):
        row = _mapping(item)
        if _text(row.get("id")) == source_id:
            return row
    return {}


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _expanded_exists(raw: str) -> bool:
    return Path(raw).is_dir()
