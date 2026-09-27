"""Operator-only SB2 configuration; no authority inferred from input documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sb.config import Config, TomlValue
from sb.life_contracts import LifeInputError, SourcePolicyV1
from sb.life_values import zone

FLAGS = frozenset(
    {
        "life_events",
        "life_timeline",
        "obsidian_view",
        "life_briefing",
        "gap_questions",
        "contextual_recall",
        "location_capture",
        "health_capture",
        "prediction",
    }
)
_ALLOWED = FLAGS | frozenset(
    {
        "sources",
        "timezone",
        "question_budget",
        "question_cooldown_hours",
        "quiet_start",
        "quiet_end",
        "client_token_env",
        "client_source_ids",
        "client_can_write",
        "view_sensitivities",
        "daily_model_calls",
    }
)


@dataclass(frozen=True, slots=True)
class LifeSettingsV1:
    flags: frozenset[str] = frozenset()
    timezone: str = "Asia/Seoul"
    question_budget: int = 3
    question_cooldown_hours: int = 72
    quiet_start: int = 22
    quiet_end: int = 8
    daily_model_calls: int = 20
    client_token_env: str | None = None
    client_source_ids: tuple[str, ...] = ()
    client_can_write: bool = False
    view_sensitivities: tuple[str, ...] = ("public", "personal")

    def require(self, feature: str) -> None:
        if feature not in self.flags:
            raise LifeInputError("LIFE_FEATURE_DISABLED")


def _mapping(config: Config) -> Mapping[str, TomlValue]:
    raw = config.raw.get("life", {})
    if not isinstance(raw, Mapping) or set(raw) - _ALLOWED:
        raise LifeInputError("LIFE_CONFIG_INVALID")
    return raw


def _integer(raw: Mapping[str, TomlValue], name: str, default: int, lower: int, upper: int) -> int:
    value = raw.get(name, default)
    if type(value) is not int or not lower <= value <= upper:
        raise LifeInputError("LIFE_CONFIG_INVALID")
    return value


def settings(config: Config) -> LifeSettingsV1:
    raw = _mapping(config)
    for flag in FLAGS:
        if type(raw.get(flag, False)) is not bool:
            raise LifeInputError("LIFE_CONFIG_INVALID")
    tz = zone(raw.get("timezone", "Asia/Seoul")).key
    token_env = raw.get("client_token_env")
    if token_env is not None and (
        not isinstance(token_env, str) or not token_env.isidentifier() or len(token_env) > 128
    ):
        raise LifeInputError("LIFE_CONFIG_INVALID")
    clients = raw.get("client_source_ids", [])
    can_write = raw.get("client_can_write", False)
    if type(can_write) is not bool:
        raise LifeInputError("LIFE_CONFIG_INVALID")
    sensitivities = raw.get("view_sensitivities", ["public", "personal"])
    if not isinstance(clients, list) or any(not isinstance(s, str) for s in clients):
        raise LifeInputError("LIFE_CONFIG_INVALID")
    if (
        not isinstance(sensitivities, list)
        or not sensitivities
        or any(s not in {"public", "personal", "sensitive", "restricted"} for s in sensitivities)
    ):
        raise LifeInputError("LIFE_CONFIG_INVALID")
    return LifeSettingsV1(
        flags=frozenset(f for f in FLAGS if raw.get(f, False)),
        timezone=tz,
        question_budget=_integer(raw, "question_budget", 3, 0, 100),
        question_cooldown_hours=_integer(raw, "question_cooldown_hours", 72, 1, 8760),
        quiet_start=_integer(raw, "quiet_start", 22, 0, 23),
        quiet_end=_integer(raw, "quiet_end", 8, 0, 23),
        daily_model_calls=_integer(raw, "daily_model_calls", 20, 0, 10000),
        client_token_env=token_env,
        client_source_ids=tuple(s for s in clients if isinstance(s, str)),
        client_can_write=can_write,
        view_sensitivities=tuple(s for s in sensitivities if isinstance(s, str)),
    )


def policies(config: Config, *, owner: str = "principal:owner") -> dict[str, SourcePolicyV1]:
    raw = _mapping(config).get("sources", {})
    if not isinstance(raw, Mapping):
        raise LifeInputError("LIFE_CONFIG_INVALID")
    access = config.source_access
    result: dict[str, SourcePolicyV1] = {}
    allowed = {"enabled", "allowed_types", "sensitivity", "external_processing", "retention_days"}
    for name, value in raw.items():
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise LifeInputError("LIFE_CONFIG_INVALID")
        binding = access.get(name)
        if binding is None:
            raise LifeInputError("LIFE_SOURCE_CLASSIFICATION_REQUIRED")
        if binding.owner != owner:
            continue
        types = value.get("allowed_types", ["note_saved", "link_saved"])
        if not isinstance(types, list) or any(not isinstance(t, str) for t in types):
            raise LifeInputError("LIFE_CONFIG_INVALID")
        enabled = value.get("enabled", False)
        sensitivity = value.get("sensitivity", "personal")
        processing = value.get("external_processing", "local_only")
        retention = value.get("retention_days", 365)
        if type(enabled) is not bool:
            raise LifeInputError("LIFE_POLICY_INVALID")
        if not isinstance(sensitivity, str):
            raise LifeInputError("LIFE_SENSITIVITY_INVALID")
        if not isinstance(processing, str):
            raise LifeInputError("LIFE_PROCESSING_POLICY_INVALID")
        if type(retention) is not int:
            raise LifeInputError("LIFE_RETENTION_INVALID")
        result[name] = SourcePolicyV1(
            source_id=name,
            scopes=(binding.owner, *binding.projects),
            enabled=enabled,
            allowed_types=tuple(t for t in types if isinstance(t, str)),
            sensitivity=sensitivity,
            external_processing=processing,
            retention_days=retention,
            policy_revision=binding.policy_revision,
        )
    return result


def policy_for(config: Config, source_id: str, *, admission: bool = True) -> SourcePolicyV1:
    opts = settings(config)
    if admission:
        opts.require("life_events")
    policy = policies(config).get(source_id)
    if policy is None:
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    if admission and not policy.enabled:
        raise LifeInputError("LIFE_SOURCE_DISABLED")
    return policy
