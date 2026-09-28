"""Life HTTP actor authorization, separate from read dispatch."""

import hmac
import os

from sb.config import Config
from sb.effect_values import JsonInput
from sb.life_actor import LifeActor
from sb.life_config import policies, settings
from sb.life_contracts import LifeInputError


def authorize(config: Config, supplied: str, admin_token: str | None) -> LifeActor | None:
    from sb.life_auth import device

    opts = settings(config)
    available = policies(config)
    if len(supplied) > 1024:
        return None
    admin = (admin_token is None and not supplied) or (
        admin_token is not None
        and hmac.compare_digest(supplied.encode(), ("Bearer " + admin_token).encode())
    )
    if admin:
        selected = tuple(available)
    else:
        registered = device(config, supplied, available)
        if registered is not None:
            device_id, selected, can_write = registered
            scopes = tuple(sorted({s for name in selected for s in available[name].scopes}))
            return LifeActor(
                selected, scopes, client=True, device_id=device_id, can_write=can_write
            )
        token = os.environ.get(opts.client_token_env, "") if opts.client_token_env else ""
        if len(token) < 32 or not hmac.compare_digest(
            supplied.encode(), ("Bearer " + token).encode()
        ):
            return None
        selected = tuple(s for s in opts.client_source_ids if s in available)
        if not selected:
            return None
    scope = tuple(sorted({scope for name in selected for scope in available[name].scopes}))
    return LifeActor(
        selected,
        scope,
        client=not admin,
        device_id="owner" if admin else "legacy-life-client",
        can_write=admin or opts.client_can_write,
    )


def require_source(actor: LifeActor, source_id: JsonInput) -> str:
    if not isinstance(source_id, str) or source_id not in actor.source_ids:
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    return source_id


def error_status(code: str) -> int:
    if code == "LIFE_DEVICE_EXPIRED_OR_REVOKED":
        return 401
    if code.startswith("LIFE_AUTH_CONFIG_"):
        return 503
    if "NOT_FOUND" in code:
        return 404
    if code in {"LIFE_SOURCE_NOT_ALLOWED", "LIFE_SOURCE_DISABLED", "LIFE_FEATURE_DISABLED"}:
        return 403
    if "CONFLICT" in code or code in {"LIFE_POLICY_CHANGED", "LIFE_EVENT_DELETED"}:
        return 409
    if code in {"LIFE_NOT_INITIALIZED", "LIFE_SCHEMA_UNSUPPORTED", "LIFE_RECORD_CORRUPT"}:
        return 503
    return 400
