"""Life CLI orchestration; pipeline entrypoints are injected by sb.cli.

Persistent reservations and delivery claims are committed before external work.
No resident worker is installed. Read commands do not create or migrate state.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from sb.config import Config
from sb.life_config import policies, settings
from sb.life_contracts import LifeInputError
from sb.life_http import LifeActor, read_endpoint, visible_events
from sb.runtime_access import read_root

READ_COMMANDS = {
    "health": "health",
    "timeline": "timeline",
    "manifest": "views/obsidian/manifest",
    "questions": "questions",
    "relations": "relations",
    "predictions": "predictions",
    "actuals": "actuals",
    "briefings": "briefings/persisted",
    "deliveries": "deliveries",
}
WRITE_COMMANDS = frozenset(
    {
        "questions-generate",
        "question-response",
        "briefing-generate",
        "tick",
        "relation-put",
        "entity-alias",
        "prediction-issue",
        "prediction-evaluate",
        "collection-status",
        "view-ack",
        "delivery-opened",
    }
)


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "life_command",
        choices=sorted(
            set(READ_COMMANDS)
            | WRITE_COMMANDS
            | {
                "import",
                "ingest",
                "recall",
                "notify",
                "model-run",
                "maintain",
                "evidence-links",
            }
        ),
    )
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--input", help="UTF-8 JSON request file; no default private file reads")
    parser.add_argument(
        "--data",
        help="Small inline JSON request; avoid secrets or private content in shell history",
    )
    parser.add_argument("--raw-file", help="Explicit source file for import")
    parser.add_argument("--format", default="life-json")
    parser.add_argument("--day")
    parser.add_argument("--slot", choices=("morning", "evening"))
    parser.add_argument("--query")
    parser.add_argument("--as-of")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Also use the explicitly configured notification transport",
    )


def bounded_file(path: str, maximum: int) -> bytes:
    candidate = Path(path)
    fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise LifeInputError("LIFE_INPUT_FILE_INVALID")
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > maximum or os.fstat(fd).st_mtime_ns != info.st_mtime_ns:
            raise LifeInputError("LIFE_INPUT_FILE_CHANGED")
        return bytes(data)
    finally:
        os.close(fd)


def actor(config: Config, sources: list[str]) -> LifeActor:
    available = policies(config)
    selected = tuple(sorted(set(sources or available)))
    if not selected or any(s not in available for s in selected):
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    scopes = tuple(sorted({v for s in selected for v in available[s].scopes}))
    return LifeActor(selected, scopes, False, "local-owner", True)


def _payload(ns: argparse.Namespace) -> dict[str, object]:
    if ns.input and ns.data:
        raise LifeInputError("LIFE_INPUT_INVALID")
    if ns.input:
        value = json.loads(bounded_file(ns.input, 2 * 1024 * 1024))
    elif ns.data:
        if len(ns.data.encode()) > 2 * 1024 * 1024:
            raise LifeInputError("LIFE_INPUT_INVALID")
        value = json.loads(ns.data)
    else:
        value = {}
    if not isinstance(value, dict):
        raise LifeInputError("LIFE_INPUT_INVALID")
    for argument, key in (
        (ns.day, "day"),
        (ns.slot, "slot"),
        (ns.query, "query"),
        (ns.as_of, "as_of"),
    ):
        if argument is not None:
            value[key] = argument
    return value


def _check(outcome: Any, result: Any) -> Any:
    if outcome.already_running:
        raise LifeInputError("LIFE_WRITER_BUSY")
    if outcome.exit_code:
        message = (outcome.failure or "LIFE_OPERATION_FAILED").split(": ")[-1]
        raise LifeInputError(
            message
            if message.startswith("LIFE_") and len(message) < 100
            else "LIFE_OPERATION_FAILED"
        )
    return result


def dispatch(
    ns: argparse.Namespace,
    config: Config,
    *,
    workflow: Callable[..., Any],
    importer: Callable[..., Any],
    ingest: Callable[..., Any],
    maintainer: Callable[..., Any],
) -> dict[str, Any]:
    from sb.life_auth import current_config

    config = current_config(config)
    principal = actor(config, ns.source)
    data = _payload(ns)
    command = ns.life_command
    common = {"source_ids": principal.source_ids, "scopes": principal.scopes}

    def write(name: str, body: dict[str, object]) -> dict[str, Any]:
        fresh = current_config(config)
        if fresh.raw != config.raw:
            raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
        return _check(*workflow(fresh, name, body, **common))

    if command == "evidence-links":
        event_id = data.get("event_id")
        if not isinstance(event_id, str) or not event_id or len(event_id) > 512:
            raise LifeInputError("LIFE_INPUT_INVALID")
        with read_root(config) as root:
            return read_endpoint(
                config,
                root,
                principal,
                "/api/life/v1/evidence-links/" + event_id,
            )
    if command in READ_COMMANDS:
        query = urlencode({k: v for k, v in data.items() if v is not None})
        with read_root(config) as root:
            return read_endpoint(
                config,
                root,
                principal,
                "/api/life/v1/" + READ_COMMANDS[command] + ("?" + query if query else ""),
            )
    if command == "recall":
        from sb.life_api_reads import recall_request

        with read_root(config) as root:
            return recall_request(config, root, principal, data, now=datetime.now(UTC))
    if command == "import":
        if len(principal.source_ids) != 1 or not ns.raw_file:
            raise LifeInputError("LIFE_IMPORT_SOURCE_REQUIRED")
        raw = bounded_file(ns.raw_file, 16 * 1024 * 1024)
        return _check(
            *importer(
                config, principal.source_ids[0], ns.format, raw, filename=Path(ns.raw_file).name
            )
        )
    if command == "ingest":
        result = ingest(config, principal.source_ids)
        _check(result, {})
        return {
            "state": result.status,
            "run_id": result.run_id,
            "written": result.written,
            "errors": result.errors,
        }
    if command == "maintain":
        return _check(*maintainer(config, source_ids=principal.source_ids, scopes=principal.scopes))
    if command in WRITE_COMMANDS:
        result = write(command.replace("-", "_"), data)
        if command == "tick" and "gap_questions" in settings(config).flags:
            result["questions"] = write("questions_generate", {})["questions"]
        if command in {"tick", "briefing-generate"} and ns.send:
            result["deliveries"] = [
                _notify(config, write, row["object_id"], principal)
                for row in result.get("briefings", [])
            ]
        return result
    if command == "notify":
        if set(data) != {"briefing_id"} or not ns.send:
            raise LifeInputError("LIFE_DELIVERY_EXPLICIT_SEND_REQUIRED")
        return _notify(config, write, data["briefing_id"], principal)
    if command == "model-run":
        return _model(config, write, data, principal)
    raise LifeInputError("LIFE_ROUTE_NOT_FOUND")


def _notify(
    config: Config, write: Callable[..., Any], briefing_id: str, principal: LifeActor
) -> dict[str, Any]:
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
        endpoint=raw.get("endpoint", ""),
        token_env=raw.get("token_env"),
        allow_private=raw.get("allow_private", False),
        timeout=raw.get("timeout", 10),
    )
    claim = write("delivery_prepare", {"briefing_id": briefing_id})
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
                LifeJournal(store).get(
                    "briefing",
                    briefing_id,
                    scopes=principal.scopes,
                    source_ids=principal.source_ids,
                    events=events,
                )
                from sb.life_delivery import evidence_still_current

                claimed = LifeJournal(store).raw("delivery", claim["object_id"])
                current = claimed is not None and evidence_still_current(
                    LifeJournal(store), claimed, now=datetime.now(UTC)
                )
            if not current:
                state, provider_id = "stale", None
            else:
                state, provider_id = send_notification(
                    channel, claim["object_id"], claim["body"]["notification"]
                )
    except LifeInputError:
        state, provider_id = "rejected", None
    result = write(
        "delivery_finish",
        {"delivery_id": claim["object_id"], "state": state, "provider_id": provider_id},
    )
    return {"state": result["body"]["state"], "delivery_id": result["object_id"], "opened": False}


def _model(
    config: Config, write: Callable[..., Any], data: dict[str, object], principal: LifeActor
) -> dict[str, Any]:
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
        or not isinstance(cfg.get("argv_template"), list)
        or not cfg["argv_template"]
        or any(not isinstance(s, str) or not s for s in cfg["argv_template"])
    ):
        raise LifeInputError("LIFE_MODEL_NOT_CONFIGURED")
    if set(data) != {"event_ids", "idempotency_key"}:
        raise LifeInputError("LIFE_MODEL_INPUT_INVALID")
    request = {
        **data,
        "external": cfg["external"],
        "estimated_tokens": cfg.get("estimated_tokens", 4096),
        "maximum_cost_micros": cfg.get("maximum_cost_micros", 0),
    }
    reservation = write("model_reserve", request)
    if not reservation["execute_allowed"]:
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
            selected = tuple(e for e in events if e.event_id in data["event_ids"])
        model = CliLLM(list(cfg["argv_template"]), attempt_limit=1)
        output = generate_after_reservation(
            reservation,
            model,
            events=selected,
            external=cfg["external"],
            scopes=principal.scopes,
            source_ids=principal.source_ids,
        )
        state = "spent"
    except LifeInputError:
        state = "unknown"
    write(
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
        "result": json.loads(output),
        "actual_usage": "not_reported",
        "reserved_bounds_charged": True,
    }


def run(ns: argparse.Namespace, config: Config, **callbacks: Any) -> int:
    try:
        result = dispatch(ns, config, **callbacks)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (LifeInputError, ValueError, TypeError, OSError) as exc:
        code = exc.code if isinstance(exc, LifeInputError) else "LIFE_CLI_FAILED"
        print(json.dumps({"state": "failed", "error": code}, ensure_ascii=False))
        return 1
