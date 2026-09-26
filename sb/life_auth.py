"""Operator-configured, expiring per-device capabilities; no new auth service."""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sb.config import Config, load_config
from sb.life_contracts import IDENTIFIER, LifeInputError
from sb.life_values import instant


def current_config(config: Config) -> Config:
    if config.source_path is None:
        return config
    if not Path(config.source_path).is_file():
        raise LifeInputError("LIFE_AUTH_CONFIG_UNAVAILABLE")
    try:
        fresh = load_config(config.source_path)
    except (OSError, ValueError) as exc:
        raise LifeInputError("LIFE_AUTH_CONFIG_UNAVAILABLE") from exc
    if Path(fresh.vault_root).absolute() != Path(config.vault_root).absolute():
        raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
    return fresh


def admin_token(fresh: Config, original: Config, server_token: str | None) -> str | None:
    del fresh, original
    # The existing HTTP server uses SB_WEB_TOKEN, not TOML web.token.
    # Never promote a config-only value into a second administrator authority,
    # or turn a formerly protected server into anonymous mode after revocation.
    active = os.environ.get("SB_WEB_TOKEN") or None
    if server_token is not None and active is None:
        raise LifeInputError("LIFE_AUTH_CONFIG_UNAVAILABLE")
    return active


def device(
    config: Config, supplied: str, available: Mapping[str, Any], *, now: datetime | None = None
) -> tuple[str, tuple[str, ...], bool] | None:
    raw = config.raw.get("life_devices", {})
    if not isinstance(raw, Mapping) or len(raw) > 100:
        raise LifeInputError("LIFE_DEVICE_CONFIG_INVALID")
    clock = now or datetime.now(UTC)
    matches = []
    for identity, entry in raw.items():
        if (
            not isinstance(identity, str)
            or IDENTIFIER.fullmatch(identity) is None
            or not isinstance(entry, Mapping)
            or set(entry) - {"token_env", "source_ids", "can_write", "expires_at", "revoked"}
        ):
            raise LifeInputError("LIFE_DEVICE_CONFIG_INVALID")
        name = entry.get("token_env")
        sources = entry.get("source_ids")
        if (
            not isinstance(name, str)
            or not name.isidentifier()
            or len(name) > 128
            or not isinstance(sources, list)
            or not sources
            or any(not isinstance(s, str) or s not in available for s in sources)
            or type(entry.get("can_write", False)) is not bool
            or type(entry.get("revoked", False)) is not bool
        ):
            raise LifeInputError("LIFE_DEVICE_CONFIG_INVALID")
        expires = instant(entry.get("expires_at"))
        token = os.environ.get(name, "")
        if len(token) >= 32 and hmac.compare_digest(
            supplied.encode(), ("Bearer " + token).encode()
        ):
            if entry.get("revoked") or clock >= expires:
                raise LifeInputError("LIFE_DEVICE_EXPIRED_OR_REVOKED")
            matches.append((identity, tuple(sorted(set(sources))), entry.get("can_write", False)))
    if len(matches) > 1:
        raise LifeInputError("LIFE_DEVICE_CONFIG_INVALID")
    return matches[0] if matches else None
