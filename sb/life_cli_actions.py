"""Explicit notification and model actions after durable workflow reservations."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from pydantic import TypeAdapter

from sb.config import Config
from sb.effect_values import JsonInput
from sb.life_actor import LifeActor
from sb.life_contracts import LifeInputError
from sb.life_fields import boolean, integer, number, string
from sb.life_journal_contracts import JournalRow
from sb.life_json import LifePayload, decode_json
from sb.life_read_visibility import visible_events
from sb.runtime_access import read_root

_JOURNAL: Final = TypeAdapter[JournalRow](JournalRow)
_NOTIFICATION: Final = TypeAdapter[dict[str, str]](dict[str, str])


def notify(
    config: Config,
    write: Callable[[str, Mapping[str, JsonInput]], LifePayload],
    briefing_id: str,
    principal: LifeActor,
) -> Mapping[str, JsonInput]:
    from sb.life_auth import current_config
    from sb.life_delivery import TransportConfig, send_notification
    from sb.store.life import read_life_store
    from sb.store.life_journal import LifeJournal

    raw = config.raw.get("life_delivery")
    if (
        not isinstance(raw, Mapping)
        or raw.get("enabled") is not True
        or set(raw) - {"enabled", "endpoint", "token_env", "allow_private", "timeout"}
        or type(raw.get("allow_private", False)) is not bool
    ):
        raise LifeInputError("LIFE_DELIVERY_NOT_CONFIGURED")
    channel = TransportConfig(
        endpoint=string(raw.get("endpoint", ""), "LIFE_DELIVERY_NOT_CONFIGURED"),
        token_env=None
        if raw.get("token_env") is None
        else string(raw.get("token_env"), "LIFE_DELIVERY_NOT_CONFIGURED"),
        allow_private=boolean(raw.get("allow_private", False), "LIFE_DELIVERY_NOT_CONFIGURED"),
        timeout=number(raw.get("timeout", 10)),
    )
    claim = _JOURNAL.validate_python(
        write("delivery_prepare", {"briefing_id": briefing_id}), strict=True
    )
    if not claim.get("send_allowed"):
        return {"state": claim["body"]["state"], "delivery_id": claim["object_id"], "sent": False}
    try:
        fresh = current_config(config)
        if fresh.raw != config.raw:
            raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
        with read_root(fresh) as root:
            events, complete = visible_events(fresh, root, principal, datetime.now(UTC))
            if not complete:
                raise LifeInputError("LIFE_WORKSET_TOO_LARGE")
            with read_life_store(root) as store:
                _ = LifeJournal(store).get(
                    "briefing",
                    briefing_id,
                    scopes=principal.scopes,
                    source_ids=principal.source_ids,
                    events=events,
                )
        state, provider_id = send_notification(
            channel,
            claim["object_id"],
            _NOTIFICATION.validate_python(claim["body"]["notification"], strict=True),
        )
    except LifeInputError:
        state, provider_id = "rejected", None
    result = _JOURNAL.validate_python(
        write(
            "delivery_finish",
            {"delivery_id": claim["object_id"], "state": state, "provider_id": provider_id},
        ),
        strict=True,
    )
    return {"state": result["body"]["state"], "delivery_id": result["object_id"], "opened": False}


def model(
    config: Config,
    write: Callable[[str, Mapping[str, JsonInput]], LifePayload],
    data: Mapping[str, JsonInput],
    principal: LifeActor,
) -> Mapping[str, JsonInput]:
    from sb.life_auth import current_config
    from sb.life_model_policy import generate_after_reservation
    from sb.llm import CliLLM

    cfg = config.raw.get("life_model")
    if (
        not isinstance(cfg, Mapping)
        or cfg.get("enabled") is not True
        or set(cfg)
        - {"enabled", "external", "argv_template", "maximum_cost_micros", "estimated_tokens"}
        or type(cfg.get("external")) is not bool
    ):
        raise LifeInputError("LIFE_MODEL_NOT_CONFIGURED")
    argv = cfg.get("argv_template")
    if not isinstance(argv, list) or not argv or any(not isinstance(s, str) or not s for s in argv):
        raise LifeInputError("LIFE_MODEL_NOT_CONFIGURED")
    if set(data) != {"event_ids", "idempotency_key"}:
        raise LifeInputError("LIFE_MODEL_INPUT_INVALID")
    request: LifePayload = {
        **data,
        "external": boolean(cfg["external"], "LIFE_MODEL_NOT_CONFIGURED"),
        "estimated_tokens": integer(cfg.get("estimated_tokens", 4096), "LIFE_MODEL_NOT_CONFIGURED"),
        "maximum_cost_micros": integer(
            cfg.get("maximum_cost_micros", 0), "LIFE_MODEL_NOT_CONFIGURED"
        ),
    }
    reservation = _JOURNAL.validate_python(write("model_reserve", request), strict=True)
    if not reservation.get("execute_allowed"):
        return {
            "state": "already_reserved",
            "reservation_id": reservation["object_id"],
            "executed": False,
        }
    output = None
    state = "unknown"
    try:
        fresh = current_config(config)
        if fresh.raw != config.raw:
            raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
        with read_root(fresh) as root:
            events, complete = visible_events(fresh, root, principal, datetime.now(UTC))
            if not complete:
                raise LifeInputError("LIFE_WORKSET_TOO_LARGE")
            event_ids = data["event_ids"]
            if not isinstance(event_ids, list):
                raise LifeInputError("LIFE_MODEL_INPUT_INVALID")
            selected = tuple(e for e in events if e.event_id in event_ids)
        model = CliLLM([string(arg, "LIFE_MODEL_NOT_CONFIGURED") for arg in argv], attempt_limit=1)
        output = generate_after_reservation(
            reservation,
            model,
            events=selected,
            external=boolean(cfg["external"], "LIFE_MODEL_NOT_CONFIGURED"),
            scopes=principal.scopes,
            source_ids=principal.source_ids,
        )
        state = "spent"
    except LifeInputError:
        state = "unknown"
    _ = write(
        "model_settle",
        {
            "reservation_id": reservation["object_id"],
            "state": state,
            "actual_tokens": 0,
            "actual_cost_micros": 0,
        },
    )
    if output is None:
        raise LifeInputError("LIFE_MODEL_UNAVAILABLE")
    return {
        "state": "generated",
        "reservation_id": reservation["object_id"],
        "result": decode_json(output),
        "actual_usage": "not_reported",
        "reserved_bounds_charged": True,
    }
