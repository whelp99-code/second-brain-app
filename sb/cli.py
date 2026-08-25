"""argparse CLI for the second-brain pipeline. Thin: parse, dispatch, print."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from sb.config import load_config
from sb.pipeline import read_status, run_all, run_brief, run_compile, run_ingest
from sb.store.ledger import rebuild_from_vault
from sb.vault import RunCommitNotFoundError, Vault, init_vault


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
    return parser


def _opt_str(ns: argparse.Namespace, name: str) -> str | None:
    value = vars(ns).get(name)
    return value if isinstance(value, str) else None


def _opt_int(ns: argparse.Namespace, name: str) -> int | None:
    value = vars(ns).get(name)
    return value if isinstance(value, int) else None


def _opt_flag(ns: argparse.Namespace, name: str) -> bool:
    return vars(ns).get(name) is True


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
        selected = None if source is None else (source,)
        outcome = run_ingest(config, selected, limit=_opt_int(ns, "limit"))
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def compile_cmd() -> int:
        outcome = run_compile(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def brief() -> int:
        outcome = run_brief(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def run() -> int:
        outcome = run_all(config)
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def status() -> int:
        print(read_status(config))
        return 0

    def rollback() -> int:
        run_id = _opt_str(ns, "run_id")
        if run_id is None:
            print("rollback requires run_id", file=sys.stderr)
            return 2
        try:
            Vault(root=Path(config.vault_root)).rollback(run_id)
        except RunCommitNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    def doctor() -> int:
        if _opt_flag(ns, "rebuild_ledger"):
            rebuild_from_vault(config.vault_root)
        _ = read_status(config)
        return 0

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
    }
    return handlers[command]()


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch one of the nine subcommands."""
    parser = _parser()
    tokens = sys.argv[1:] if argv is None else argv
    try:
        ns = parser.parse_args(tokens)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    if not tokens:
        _ = parser.print_help()
        return 2
    return _dispatch(Command(tokens[0]), ns)


if __name__ == "__main__":
    raise SystemExit(main())
