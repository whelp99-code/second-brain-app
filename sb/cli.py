"""argparse CLI for the second-brain pipeline. Thin: parse, dispatch, print."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import cast

from sb.cli_cancellation import apply_cancellation
from sb.cli_requests import apply_requests_once
from sb.config import ConfigValueError, load_config
from sb.generation_runtime import GenerationMutationService, GenerationOperation
from sb.generations import GenerationError
from sb.governance import GovernanceError, collect_orphans, retention_report, source_status
from sb.inbox import RememberRejected
from sb.metrics import record_command
from sb.metrics import summary as metrics_summary
from sb.ops import (
    OperationError,
    migrate_status,
    restore_backup,
    retry_failed,
    status_snapshot,
)
from sb.ops import (
    doctor as run_doctor,
)
from sb.pipeline import read_status, run_all, run_brief, run_compile, run_ingest
from sb.runtime_access import mutate_root, read_config
from sb.search import SearchIndex
from sb.search_errors import GenerationIndexError, SearchQueryError
from sb.store.ledger import rebuild_from_vault
from sb.vault import Vault, VaultLintError, init_vault


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
    RETRY = "retry"
    BACKUP = "backup"
    VERIFY_BACKUP = "verify-backup"
    RESTORE = "restore"
    MIGRATE = "migrate"
    RESOLVE = "resolve"
    WEB = "web"
    SOURCES = "sources"
    RETENTION = "retention"
    GC = "gc"
    METRICS = "metrics"
    APPLY_CANCELLATION = "apply-cancellation"
    APPLY_REQUESTS = "apply-requests"
    MAINTAIN = "maintain"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb")
    sub = parser.add_subparsers(dest="command")
    _ = sub.add_parser(Command.INIT.value)
    ingest = sub.add_parser(Command.INGEST.value)
    _ = ingest.add_argument("--source")
    _ = ingest.add_argument("--limit", type=int,
                           help="maximum source items attempted; the configured unit budget also applies")
    compile_cmd = sub.add_parser(Command.COMPILE.value)
    _ = compile_cmd.add_argument("--llm")
    _ = compile_cmd.add_argument("--dry-run", action="store_true")
    _ = compile_cmd.add_argument("--state-report", action="store_true")
    brief = sub.add_parser(Command.BRIEF.value)
    _ = brief.add_argument("--llm")
    _ = sub.add_parser(Command.RUN.value)
    status = sub.add_parser(Command.STATUS.value)
    _ = status.add_argument("--json", action="store_true")
    rollback = sub.add_parser(Command.ROLLBACK.value)
    _ = rollback.add_argument("run_id")
    doctor = sub.add_parser(Command.DOCTOR.value)
    _ = doctor.add_argument("--rebuild-ledger", action="store_true")
    _ = doctor.add_argument("--json", action="store_true")
    _ = sub.add_parser(Command.MCP.value)
    search_cmd = sub.add_parser(Command.SEARCH.value)
    _ = search_cmd.add_argument("query")
    _ = search_cmd.add_argument("--limit", type=int)
    _ = search_cmd.add_argument("--json", action="store_true")
    _ = search_cmd.add_argument(
        "--kind",
        action="append",
        choices=("wiki", "daily", "conflicts"),
    )
    _ = search_cmd.add_argument("--status")
    _ = search_cmd.add_argument("--updated-from")
    _ = search_cmd.add_argument("--updated-to")
    _ = search_cmd.add_argument(
        "--scope",
        choices=("active", "candidate", "reference"),
        default=None,
    )
    remember = sub.add_parser(Command.REMEMBER.value)
    _ = remember.add_argument("content")
    _ = remember.add_argument("--title")
    cancellation = sub.add_parser(Command.APPLY_CANCELLATION.value)
    _ = cancellation.add_argument("--intent-id", required=True)
    apply_requests = sub.add_parser(Command.APPLY_REQUESTS.value)
    _ = apply_requests.add_argument("--once", action="store_true")
    _ = apply_requests.add_argument("--test-control-socket")
    maintain = sub.add_parser(Command.MAINTAIN.value)
    _ = maintain.add_argument("--once", action="store_true")
    retry = sub.add_parser(Command.RETRY.value)
    _ = retry.add_argument("--stage", choices=("compile", "conflict", "brief"))
    _ = retry.add_argument("--limit", type=int)
    backup = sub.add_parser(Command.BACKUP.value)
    _ = backup.add_argument("destination", nargs="?")
    verification = sub.add_parser(Command.VERIFY_BACKUP.value)
    _ = verification.add_argument("archive")
    restore = sub.add_parser(Command.RESTORE.value)
    _ = restore.add_argument("archive")
    _ = restore.add_argument("--to")
    _ = restore.add_argument("--force", action="store_true")
    migrate = sub.add_parser(Command.MIGRATE.value)
    group = migrate.add_mutually_exclusive_group()
    _ = group.add_argument("--check", action="store_true")
    _ = group.add_argument("--apply", action="store_true")
    resolve = sub.add_parser(Command.RESOLVE.value)
    _ = resolve.add_argument("conflict_id")
    _ = resolve.add_argument(
        "--decision",
        required=True,
        choices=("keep-left", "keep-right", "note"),
    )
    _ = resolve.add_argument("--note", default="")
    web = sub.add_parser(Command.WEB.value)
    _ = web.add_argument("--host", default="127.0.0.1")
    _ = web.add_argument("--port", type=int, default=8765)
    sources = sub.add_parser(Command.SOURCES.value)
    _ = sources.add_argument("--json", action="store_true")
    retention = sub.add_parser(Command.RETENTION.value)
    _ = retention.add_argument("--json", action="store_true")
    gc = sub.add_parser(Command.GC.value)
    _ = gc.add_argument("--apply", action="store_true")
    _ = gc.add_argument("--confirm", action="store_true")
    _ = gc.add_argument("--json", action="store_true")
    metrics = sub.add_parser(Command.METRICS.value)
    _ = metrics.add_argument("--limit", type=int, default=1000)
    _ = metrics.add_argument("--json", action="store_true")
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
        selected = (source,) if source is not None else config.configured_source_ids
        outcome = run_ingest(config, selected, limit=_opt_int(ns, "limit"))
        if outcome.failure is not None:
            print(outcome.failure, file=sys.stderr)
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def compile_cmd() -> int:
        dry = _opt_flag(ns, "dry_run")
        report = _opt_flag(ns, "state_report")
        if dry or report:
            from sb.compile import compile_state_report

            payload = compile_state_report(config, dry_run=dry, project=report)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        outcome = run_compile(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def brief() -> int:
        outcome = run_brief(config, llm_mode=_opt_str(ns, "llm") or "cli")
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def run() -> int:
        outcome = run_all(config, config.configured_source_ids)
        if outcome.failure is not None:
            print(outcome.failure, file=sys.stderr)
        return _print_outcome(outcome.already_running, outcome.exit_code)

    def status() -> int:
        if _opt_flag(ns, "json"):
            print(json.dumps(status_snapshot(config), ensure_ascii=False, indent=2))
            return 0
        print(read_status(config))
        return 0

    def rollback() -> int:
        print("ROLLBACK_REQUIRES_GENERATION_AUTHORITY", file=sys.stderr)
        return 1

    def doctor() -> int:
        if _opt_flag(ns, "rebuild_ledger"):
            mutate_root(config, GenerationOperation.EFFECT, rebuild_from_vault)
            with read_config(config) as snapshot:
                checks = run_doctor(snapshot)
        else:
            checks = run_doctor(config)
        if _opt_flag(ns, "json"):
            print(json.dumps([check.as_dict() for check in checks], ensure_ascii=False, indent=2))
        else:
            for check in checks:
                line = f"{check.status.upper():4} {check.name}: {check.detail}"
                print(line, file=sys.stderr if check.status == "fail" else sys.stdout)
        return 1 if any(check.status == "fail" for check in checks) else 0

    def search() -> int:
        query = _opt_str(ns, "query")
        if query is None or not query.strip():
            print("search requires a query", file=sys.stderr)
            return 2
        raw_kinds = vars(ns).get("kind")
        kinds = (
            tuple(item for item in cast(list[object], raw_kinds) if isinstance(item, str))
            if isinstance(raw_kinds, list)
            else None
        )
        explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
        hits = SearchIndex(vault_root=Path(config.vault_root), registry_path=explicit, hybrid=config.search_hybrid,
                           min_similarity=config.search_min_similarity).search(
            query,
            _opt_int(ns, "limit") or 10,
            kinds=kinds,
            status=_opt_str(ns, "status"),
            updated_from=_opt_str(ns, "updated_from"),
            updated_to=_opt_str(ns, "updated_to"),
            scope=_opt_str(ns, "scope") or ("reference" if (Path(config.vault_root) / "generation.json").is_file() else "active"),
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
        mutations = GenerationMutationService.from_config(config)
        try:
            rel = mutations.remember(content, _opt_str(ns, "title"), datetime.now(UTC))
        except RememberRejected as exc:
            print(str(exc), file=sys.stderr)
            return 1
        finally:
            mutations.close()
        print(rel.as_posix())
        return 0

    def maintain() -> int:
        if not _opt_flag(ns, "once"):
            print("maintain requires --once", file=sys.stderr)
            return 2
        mutations = GenerationMutationService.from_config(config)
        try:
            result = mutations.maintain(datetime.now(UTC))
        finally:
            mutations.close()
        print(
            json.dumps(
                {"disposed_exports": len(result.disposed_export_digests),
                 "disposed_staging": len(result.disposed_staging_keys)},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0

    def apply_requests() -> int:
        if not _opt_flag(ns, "once"):
            print("apply-requests requires --once", file=sys.stderr)
            return 2
        return apply_requests_once(config, _opt_str(ns, "test_control_socket"))

    def retry() -> int:
        changed = mutate_root(config, GenerationOperation.EFFECT, lambda root: retry_failed(
            root, stage=_opt_str(ns, "stage"), limit=_opt_int(ns, "limit"),
        ))
        print(f"requeued={changed}")
        return 0

    def backup() -> int:
        destination = _opt_str(ns, "destination")
        if destination is None:
            stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
            destination_path = (
                Path(config.backup_root) / f"second-brain-{stamp}.tar.gz"
            )
        else:
            destination_path = Path(destination)
        from sb.runtime_backup import backup_runtime, verify_runtime_backup

        result = backup_runtime(config, destination_path)
        verification = verify_runtime_backup(config, result.archive)
        print(
            json.dumps(
                {
                    "archive": str(result.archive),
                    "checksum": result.checksum,
                    "verification": verification.model_dump(mode="json"),
                    "files": result.files,
                    "bytes": result.bytes,
                },
                ensure_ascii=False,
            )
        )
        return 0

    def verify_backup_command() -> int:
        from sb.runtime_backup import verify_runtime_backup

        archive = _opt_str(ns, "archive")
        assert archive is not None
        result = verify_runtime_backup(config, Path(archive))
        print(result.model_dump_json())
        return 0

    def restore() -> int:
        archive = _opt_str(ns, "archive")
        if archive is None:
            print("restore requires archive", file=sys.stderr)
            return 2
        destination = _opt_str(ns, "to") or config.vault_root
        if Path(destination).is_symlink() or Path(destination).absolute() == Path(config.vault_root).absolute() and "share_root" in config.raw:
            print("RESTORE_REQUIRES_ISOLATED_DESTINATION: use --to with a new directory", file=sys.stderr)
            return 1
        result = restore_backup(archive, destination, force=_opt_flag(ns, "force"))
        print(
            json.dumps(
                {
                    "destination": str(result.destination),
                    "files": result.files,
                    "bytes": result.bytes,
                    "previous": None if result.previous is None else str(result.previous),
                },
                ensure_ascii=False,
            )
        )
        return 0

    def migrate() -> int:
        result = (mutate_root(config, GenerationOperation.EFFECT,
                              lambda root: migrate_status(root, apply=True))
                  if _opt_flag(ns, "apply") else migrate_status(config.vault_root, apply=False))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    def resolve() -> int:
        conflict_id = _opt_str(ns, "conflict_id")
        decision = _opt_str(ns, "decision")
        note = _opt_str(ns, "note") or ""
        if conflict_id is None or decision is None:
            print("resolve requires conflict_id and decision", file=sys.stderr)
            return 2
        try:
            commit = mutate_root(config, GenerationOperation.EFFECT,
                                 lambda root: Vault(root=root).resolve_conflict(
                                     conflict_id, decision, note, f"manual-{conflict_id}"))
        except (FileNotFoundError, ValueError, VaultLintError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(commit or "unchanged")
        return 0

    def web() -> int:
        from sb.web import build_server

        host = _opt_str(ns, "host") or "127.0.0.1"
        port = _opt_int(ns, "port") or 8765
        try:
            server = build_server(config, host, port)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"http://{host}:{server.server_address[1]}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
        finally:
            server.server_close()
        return 0

    def sources() -> int:
        rows = source_status(config)
        if _opt_flag(ns, "json"):
            print(json.dumps(list(rows), ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("no configured sources")
            return 0
        for row in rows:
            print(
                f"{row['id']} adapter={row['adapter']} root={row['root']} "
                + f"exists={row['root_exists']} llm_policy={row['llm_policy']} "
                + f"sensitive={row['sensitive']}"
            )
        return 0

    def retention() -> int:
        report = retention_report(config.vault_root)
        if _opt_flag(ns, "json"):
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(
                f"raw_blobs={report.raw_blobs} raw_bytes={report.raw_bytes} "
                + f"protected={report.protected_blobs} "
                + f"orphans={len(report.orphan_blobs)} invalid={len(report.invalid_blobs)}"
            )
        return 0

    def gc() -> int:
        report = (mutate_root(config, GenerationOperation.EFFECT,
                              lambda root: collect_orphans(root, apply=True,
                                                           confirmed=_opt_flag(ns, "confirm")))
                  if _opt_flag(ns, "apply") else collect_orphans(config.vault_root, apply=False,
                                                               confirmed=_opt_flag(ns, "confirm")))
        if _opt_flag(ns, "json"):
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(
                f"remaining_orphans={len(report.orphan_blobs)} "
                + f"invalid={len(report.invalid_blobs)}"
            )
        return 0

    def metrics() -> int:
        report = metrics_summary(config.vault_root, _opt_int(ns, "limit") or 1000)
        if _opt_flag(ns, "json"):
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(
                f"total={report.total} failures={report.failures} "
                + f"average_ms={report.average_ms} p95_ms={report.p95_ms} "
                + f"commands={report.commands}"
            )
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
        Command.SEARCH: search,
        Command.REMEMBER: remember,
        Command.RETRY: retry,
        Command.BACKUP: backup,
        Command.VERIFY_BACKUP: verify_backup_command,
        Command.RESTORE: restore,
        Command.MIGRATE: migrate,
        Command.RESOLVE: resolve,
        Command.WEB: web,
        Command.SOURCES: sources,
        Command.RETENTION: retention,
        Command.GC: gc,
        Command.METRICS: metrics,
        Command.APPLY_CANCELLATION: lambda: apply_cancellation(config, _opt_str(ns, "intent_id") or ""),
        Command.APPLY_REQUESTS: apply_requests,
        Command.MAINTAIN: maintain,
    }
    started = monotonic()
    exit_code = 1
    try:
        read_only = command in {
            Command.STATUS, Command.SEARCH, Command.SOURCES, Command.RETENTION, Command.METRICS,
        } or (
            command == Command.DOCTOR and not _opt_flag(ns, "rebuild_ledger")
        ) or (
            command in {Command.GC, Command.MIGRATE} and not _opt_flag(ns, "apply")
        ) or (command == Command.COMPILE and (
            _opt_flag(ns, "dry_run") or _opt_flag(ns, "state_report")
        ))
        if read_only:
            with read_config(config) as snapshot:
                config = snapshot
                exit_code = handlers[command]()
        else:
            exit_code = handlers[command]()
        return exit_code
    finally:
        root = Path(config.vault_root)
        if root.is_dir():
            try:
                record_command(root, command.value, exit_code, (monotonic() - started) * 1000)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch a second-brain command."""
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
    except (OperationError, VaultLintError, GovernanceError, SearchQueryError, ConfigValueError,
            GenerationError, GenerationIndexError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
