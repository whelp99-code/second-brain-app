"""Life CLI orchestration; pipeline entrypoints are injected by sb.cli.

Persistent reservations and delivery claims are committed before external work.
No resident worker is installed. Read commands do not create or migrate state.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Unpack
from urllib.parse import urlencode

from pydantic import TypeAdapter

from sb.config import Config
from sb.effect_values import JsonInput, JsonObject
from sb.life_cli_actions import model as _model
from sb.life_cli_actions import notify as _notify
from sb.life_cli_contracts import (
    Callbacks,
    Importer,
    Ingester,
    LifeArguments,
    LifeRunOutcome,
    Maintainer,
    Workflow,
)
from sb.life_config import policies, settings
from sb.life_contracts import LifeInputError
from sb.life_fields import string
from sb.life_http import LifeActor, read_endpoint
from sb.life_journal_contracts import JournalRow
from sb.life_json import LifePayload, decode_json
from sb.runtime_access import read_root

_ARGUMENTS: Final = TypeAdapter[LifeArguments](LifeArguments)
_JOURNAL: Final = TypeAdapter[JournalRow](JournalRow)
_NOTIFICATION: Final = TypeAdapter[dict[str, str]](dict[str, str])

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
    _ = parser.add_argument(
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
    _ = parser.add_argument("--source", action="append", default=[])
    _ = parser.add_argument(
        "--input", help="UTF-8 JSON request file; no default private file reads"
    )
    _ = parser.add_argument(
        "--data",
        help="Small inline JSON request; avoid secrets or private content in shell history",
    )
    _ = parser.add_argument("--raw-file", help="Explicit source file for import")
    _ = parser.add_argument("--format", default="life-json")
    _ = parser.add_argument("--day")
    _ = parser.add_argument("--slot", choices=("morning", "evening"))
    _ = parser.add_argument("--query")
    _ = parser.add_argument("--as-of")
    _ = parser.add_argument(
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


def _payload(ns: LifeArguments) -> JsonObject:
    if ns["input"] and ns["data"]:
        raise LifeInputError("LIFE_INPUT_INVALID")
    if ns["input"]:
        value = decode_json(bounded_file(ns["input"], 2 * 1024 * 1024))
    elif ns["data"]:
        if len(ns["data"].encode()) > 2 * 1024 * 1024:
            raise LifeInputError("LIFE_INPUT_INVALID")
        value = decode_json(ns["data"])
    else:
        value = {}
    if not isinstance(value, dict):
        raise LifeInputError("LIFE_INPUT_INVALID")
    for argument, key in (
        (ns["day"], "day"),
        (ns["slot"], "slot"),
        (ns["query"], "query"),
        (ns["as_of"], "as_of"),
    ):
        if argument is not None:
            value[key] = argument
    return value


def _check[T](outcome: LifeRunOutcome, result: T) -> T:
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
    namespace: argparse.Namespace,
    config: Config,
    *,
    workflow: Workflow,
    importer: Importer,
    ingest: Ingester,
    maintainer: Maintainer,
) -> Mapping[str, JsonInput]:
    from sb.life_auth import current_config

    ns = _ARGUMENTS.validate_python(vars(namespace), strict=True)
    config = current_config(config)
    principal = actor(config, ns["source"])
    data = _payload(ns)
    command = ns["life_command"]

    def write(name: str, body: Mapping[str, JsonInput]) -> LifePayload:
        fresh = current_config(config)
        if fresh.raw != config.raw:
            raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
        return _check(
            *workflow(fresh, name, body, source_ids=principal.source_ids, scopes=principal.scopes)
        )

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
        if len(principal.source_ids) != 1 or not ns["raw_file"]:
            raise LifeInputError("LIFE_IMPORT_SOURCE_REQUIRED")
        raw = bounded_file(ns["raw_file"], 16 * 1024 * 1024)
        return _check(
            *importer(
                config,
                principal.source_ids[0],
                ns["format"],
                raw,
                filename=Path(ns["raw_file"]).name,
            )
        )
    if command == "ingest":
        result = ingest(config, principal.source_ids)
        _ = _check(result, None)
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
        if command in {"tick", "briefing-generate"} and ns["send"]:
            briefings = result.get("briefings", [])
            if not isinstance(briefings, list):
                raise LifeInputError("LIFE_RECORD_CORRUPT")
            result["deliveries"] = [
                _notify(
                    config,
                    write,
                    _JOURNAL.validate_python(row, strict=True)["object_id"],
                    principal,
                )
                for row in briefings
            ]
        return result
    if command == "notify":
        if set(data) != {"briefing_id"} or not ns["send"]:
            raise LifeInputError("LIFE_DELIVERY_EXPLICIT_SEND_REQUIRED")
        return _notify(config, write, string(data["briefing_id"]), principal)
    if command == "model-run":
        return _model(config, write, data, principal)
    raise LifeInputError("LIFE_ROUTE_NOT_FOUND")


def run(ns: argparse.Namespace, config: Config, **callbacks: Unpack[Callbacks]) -> int:
    try:
        result = dispatch(ns, config, **callbacks)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (LifeInputError, ValueError, TypeError, OSError) as exc:
        code = exc.code if isinstance(exc, LifeInputError) else "LIFE_CLI_FAILED"
        print(json.dumps({"state": "failed", "error": code}, ensure_ascii=False))
        return 1
