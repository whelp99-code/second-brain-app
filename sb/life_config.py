"""Strict opt-in configuration for life features; no credentials are stored here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sb.life_contracts import (
    SENSITIVITIES,
    LifeError,
    LifePrincipal,
    SourcePolicyV1,
    enum,
    identifier,
    instant,
    integer,
    object_fields,
    timezone_name,
)

FEATURES = frozenset(
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
OPERATIONS = frozenset({"read", "capture", "correct", "forget", "answer", "run", "ack", "predict"})


@dataclass(frozen=True, slots=True)
class ClientPolicy:
    client_id: str
    token_env: str
    scopes: tuple[str, ...]
    source_ids: tuple[str, ...]
    operations: tuple[str, ...]
    max_sensitivity: str
    expires_at: str | None = None

    def principal(self, now: datetime) -> LifePrincipal:
        if self.expires_at is not None and now >= instant(self.expires_at):
            raise LifeError("LIFE_SESSION_EXPIRED", 401)
        return LifePrincipal(
            self.client_id, self.scopes, self.source_ids, self.operations, self.max_sensitivity
        )


@dataclass(frozen=True, slots=True)
class LifeSettings:
    features: frozenset[str] = frozenset()
    sources: tuple[SourcePolicyV1, ...] = ()
    clients: tuple[ClientPolicy, ...] = ()
    timezone: str = "Asia/Seoul"
    max_batch: int = 100
    question_budget: int = 3
    question_cooldown_hours: int = 72
    quiet_start: int = 22
    quiet_end: int = 8
    prediction_min_samples: int = 20
    manifest_page_size: int = 100
    max_events: int = 100000

    def enabled(self, feature: str) -> bool:
        return "life_events" in self.features and feature in self.features

    def require(self, feature: str) -> None:
        if not self.enabled(feature):
            raise LifeError("LIFE_FEATURE_DISABLED", 404)

    @property
    def policies(self) -> dict[str, SourcePolicyV1]:
        return {source.source_id: source for source in self.sources}

    def source(self, source_id: str) -> SourcePolicyV1:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise LifeError("LIFE_SOURCE_FORBIDDEN", 403)

    def owner(self) -> LifePrincipal:
        return LifePrincipal(
            "local-owner",
            tuple(sorted({s.scope for s in self.sources})),
            tuple(s.source_id for s in self.sources),
            tuple(sorted(OPERATIONS)),
            "restricted",
        )


def _names(value: Any, *, max_items: int = 64) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise LifeError("LIFE_CONFIG_INVALID")
    result = tuple(identifier(item) for item in value)
    if len(set(result)) != len(result):
        raise LifeError("LIFE_CONFIG_INVALID")
    return result


def parse_settings(raw: Mapping[str, Any]) -> LifeSettings:
    section = raw.get("life")
    if section is None:
        return LifeSettings()
    obj = object_fields(
        section,
        {
            "features",
            "sources",
            "clients",
            "timezone",
            "max_batch",
            "question_budget",
            "question_cooldown_hours",
            "quiet_start",
            "quiet_end",
            "prediction_min_samples",
            "manifest_page_size",
            "max_events",
        },
    )
    flags = object_fields(obj.get("features", {}), set(FEATURES))
    if any(type(value) is not bool for value in flags.values()):
        raise LifeError("LIFE_CONFIG_INVALID")
    active = frozenset(key for key, value in flags.items() if value)
    if active and "life_events" not in active:
        raise LifeError("LIFE_CONFIG_DEPENDENCY")
    sources = obj.get("sources", [])
    clients = obj.get("clients", [])
    if (
        not isinstance(sources, list)
        or len(sources) > 64
        or not isinstance(clients, list)
        or len(clients) > 64
    ):
        raise LifeError("LIFE_CONFIG_INVALID")
    source_policies: list[SourcePolicyV1] = []
    for source in sources:
        row = object_fields(
            source,
            {"id", "scope", "sensitivity", "external_processing", "enabled", "health_types"},
            {"id", "scope"},
        )
        source_policies.append(
            SourcePolicyV1(
                identifier(row["id"]),
                identifier(row["scope"]),
                enum(row.get("sensitivity", "personal"), SENSITIVITIES),
                enum(
                    row.get("external_processing", "local_only"),
                    ("local_only", "explicitly_allowed"),
                ),
                row.get("enabled", False),
                _names(row.get("health_types", [])),
            )
        )
    source_ids = {source.source_id for source in source_policies}
    if len(source_ids) != len(source_policies) or (active and not source_ids):
        raise LifeError("LIFE_CONFIG_INVALID")
    source_scopes = {source.scope for source in source_policies}
    client_policies: list[ClientPolicy] = []
    for client in clients:
        row = object_fields(
            client,
            {
                "id",
                "token_env",
                "scopes",
                "source_ids",
                "operations",
                "max_sensitivity",
                "expires_at",
            },
            {"id", "token_env", "scopes", "source_ids"},
        )
        env = identifier(row["token_env"])
        if not env.startswith("SB_LIFE_") or not all(
            c.isupper() or c.isdigit() or c == "_" for c in env
        ):
            raise LifeError("LIFE_TOKEN_ENV_INVALID")
        scopes, allowed_sources = _names(row["scopes"]), _names(row["source_ids"])
        operations = _names(row.get("operations", ["read", "ack"]))
        if (
            set(scopes) - source_scopes
            or set(allowed_sources) - source_ids
            or set(operations) - OPERATIONS
        ):
            raise LifeError("LIFE_CONFIG_INVALID")
        expires = row.get("expires_at")
        if expires is not None:
            instant(expires)
        client_policies.append(
            ClientPolicy(
                identifier(row["id"]),
                env,
                scopes,
                allowed_sources,
                operations,
                enum(row.get("max_sensitivity", "personal"), SENSITIVITIES),
                expires,
            )
        )
    if len({c.client_id for c in client_policies}) != len(client_policies):
        raise LifeError("LIFE_CONFIG_INVALID")
    if len({c.token_env for c in client_policies}) != len(client_policies):
        raise LifeError("LIFE_CONFIG_INVALID")
    return LifeSettings(
        active,
        tuple(source_policies),
        tuple(client_policies),
        timezone_name(obj.get("timezone", "Asia/Seoul")),
        integer(obj.get("max_batch", 100), minimum=1, maximum=100),
        integer(obj.get("question_budget", 3), maximum=20),
        integer(obj.get("question_cooldown_hours", 72), maximum=8760),
        integer(obj.get("quiet_start", 22), maximum=23),
        integer(obj.get("quiet_end", 8), maximum=23),
        integer(obj.get("prediction_min_samples", 20), minimum=2, maximum=10000),
        integer(obj.get("manifest_page_size", 100), minimum=1, maximum=100),
        integer(obj.get("max_events", 100000), minimum=1, maximum=1000000),
    )
