"""argparse CLI for the second-brain pipeline. Thin: parse, dispatch, print."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.config import load_config
from sb.inbox import RememberRejected, write_inbox
from sb.pipeline import audit_citations, read_status, run_all, run_brief, run_compile, run_ingest
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import SearchIndex
from sb.store.ledger import rebuild_from_vault
from sb.vault import VaultLintError, init_vault


class Command(StrEnum):
    INIT = "init"
    INGEST = "ingest"
    COMPILE = "compile"
    BRIEF = "brief"
    RUN = "run"
    STATUS = "status"
    ROLLBACK = "rollback"
    DOCTOR = "doctor"
    MCP = "mcp"
    SEARCH = "search"
    REMEMBER = "remember"
    APPLY_REQUESTS = "apply-requests"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb")
    sub = parser.add_subparsers(dest="command")
    _ = sub.add_parser(Command.INIT.value)
    ingest = sub.add_parser(Command.INGEST.value)
    _ = ingest.add_argument("--source")
    _ = ingest.add_argument("--limit", type=int)
    compile_cmd = sub.add_parser(Command.COMPILE.value)
    _ = compile_cmd.add_argument("--llm")
    brief = sub.add_parser(Command.BRIEF.value)
    _ = brief.add_argument("--llm")
    _ = sub.add_parser(Command.RUN.value)
    _ = sub.add_parser(Command.STATUS.value)
    rollback = sub.add_parser(Command.ROLLBACK.value)
    _ = rollback.add_argument("run_id")
    doctor = sub.add_parser(Command.DOCTOR.value)
    _ = doctor.add_argument("--rebuild-ledger", action="store_true")
    _ = sub.add_parser(Command.MCP.value)
    search_cmd = sub.add_parser(Command.SEARCH.value)
    _ = search_cmd.add_argument("query")
    _ = search_cmd.add_argument("--limit", type=int)
    _ = search_cmd.add_argument("--json", action="store_true")
    remember = sub.add_parser(Command.REMEMBER.value)
    _ = remember.add_argument("content")
    _ = remember.add_argument("--title")
    apply_requests = sub.add_parser(Command.APPLY_REQUESTS.value)
    _ = apply_requests.add_argument("--once", action="store_true")
    return parser


def _opt_str(ns: argparse.Namespace, name: str) -> str | None:
    value = vars(ns).get(name)
    return value if isinstance(value, str) else None


def _opt_int(ns: argparse.Namespace, name: str) -> int | None:
    value = vars(ns).get(name)
    return value if isinstance(value, int) else None


def _opt_flag(ns: argparse.Namespace, name: str) -> bool:
    return vars(ns).get(name) is True


def _configured_sources() -> tuple[str, ...] | None:
    path = os.environ.get("SB_CONFIG")
    if path is None:
        return None
    names: list[str] = []
    config_path = Path(path)
    if not config_path.is_file():
        return None
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("id =", "adapter =", "type =")):
            names.append(stripped.split("=", 1)[1].strip().strip('"'))
    return tuple(names) or None


def _print_outcome(already_running: bool, exit_code: int) -> int:
    if already_running:
        print("already running")
        return 0
    return exit_code


def _mcp() -> int:
    if importlib.util.find_spec("sb.mcp") is None:
        print("mcp not available")
        return 1
    completed = subprocess.run([sys.executable, "-m", "sb.mcp"], check=False)
    return int(completed.returncode)


def _dispatch(command: Command, ns: argparse.Namespace) -> int:
    config = load_config()

    def init() -> int:
        _ = init_vault(config.vault_root)
        return 0

    def ingest() -> int:
        source = _opt_str(ns, "source")
        selected = (source,) if source is not None else _configured_sources()
        outcome = run_ingest(config, selected, limit=_opt_int(ns, "limit"))
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def compile_cmd() -> int:
        outcome = run_compile(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def brief() -> int:
        outcome = run_brief(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def run() -> int:
        outcome = run_all(config, _configured_sources())
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def status() -> int:
        print(read_status(config))
        return 0

    def rollback() -> int:
        print("ROLLBACK_REQUIRES_GENERATION_AUTHORITY", file=sys.stderr)
        return 1

    def doctor() -> int:
        if _opt_flag(ns, "rebuild_ledger"):
            rebuild_from_vault(config.vault_root)
        reasons = audit_citations(Path(config.vault_root))
        if reasons:
            print("\n".join(reasons), file=sys.stderr)
            return 1
        return 0

    def search() -> int:
        query = _opt_str(ns, "query")
        if query is None or not query.strip():
            print("search requires a query", file=sys.stderr)
            return 2
        hits = SearchIndex(vault_root=Path(config.vault_root)).search(
            query, _opt_int(ns, "limit") or 10
        )
        if _opt_flag(ns, "json"):
            print(json.dumps([hit.as_dict() for hit in hits], ensure_ascii=False, indent=2))
            return 0
        if not hits:
            print("no match")
            return 0
        for hit in hits:
            print(f"{hit.page_id} — {hit.section}")
            print(f"  {hit.snippet}")
        return 0

    def remember() -> int:
        content = _opt_str(ns, "content")
        if content is None or not content.strip():
            print("remember requires content", file=sys.stderr)
            return 2
        try:
            rel = write_inbox(Path(config.vault_root), content, _opt_str(ns, "title"))
        except RememberRejected as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(rel.as_posix())
        return 0

    def apply_requests() -> int:
        if not _opt_flag(ns, "once"):
            print("apply-requests requires --once", file=sys.stderr)
            return 2
        configured_jarvis_keys = config.jarvis_public_keys
        if (
            not configured_jarvis_keys
            or config.provider_signing_key_id is None
            or config.provider_private_key is None
        ):
            print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
            return 1
        try:
            jarvis_keys = {
                key_id: Ed25519PublicKey.from_public_bytes(
                    base64.urlsafe_b64decode(encoded + "==")
                )
                for key_id, encoded in configured_jarvis_keys.items()
                if key_id not in config.revoked_jarvis_signing_key_ids
            }
            external_keys = {
                key_id: Ed25519PublicKey.from_public_bytes(
                    base64.urlsafe_b64decode(encoded + "==")
                )
                for key_id, encoded in config.external_erasure_public_keys.items()
            }
            provider_key = Ed25519PrivateKey.from_private_bytes(
                base64.urlsafe_b64decode(config.provider_private_key + "==")
            )
        except ValueError:
            print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
            return 1
        if not jarvis_keys:
            print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
            return 1
        executor = RequestExecutor(
            ExecutorConfig(
                request_root=Path(config.request_root),
                state_root=Path(config.state_root),
                share_root=Path(config.share_root),
                export_root=Path(config.export_root),
                backup_root=Path(config.backup_root),
                provider_instance_id=config.provider_instance_id,
                provider_release_sha=config.provider_release_sha,
                provider_signing_key_id=config.provider_signing_key_id,
                provider_signing_key=provider_key,
                jarvis_public_keys=jarvis_keys,
                external_public_keys=external_keys,
            )
        )
        try:
            result = executor.apply_once()
        finally:
            executor.close()
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0 if result.state in {"idle", "proved", "reconciling"} else 1

    handlers: dict[Command, Callable[[], int]] = {
        Command.INIT: init,
        Command.INGEST: ingest,
        Command.COMPILE: compile_cmd,
        Command.BRIEF: brief,
        Command.RUN: run,
        Command.STATUS: status,
        Command.ROLLBACK: rollback,
        Command.DOCTOR: doctor,
        Command.MCP: _mcp,
        Command.SEARCH: search,
        Command.REMEMBER: remember,
        Command.APPLY_REQUESTS: apply_requests,
    }
    return handlers[command]()


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch one of the eleven subcommands."""
    parser = _parser()
    tokens = sys.argv[1:] if argv is None else argv
    try:
        ns = parser.parse_args(tokens)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    if not tokens:
        _ = parser.print_help()
        return 2
    try:
        return _dispatch(Command(tokens[0]), ns)
    except VaultLintError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
