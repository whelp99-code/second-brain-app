"""Command-line entry point for Phone History operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from phone_history.api import build_server
from phone_history.config import Settings
from phone_history.service import PhoneHistoryService


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="phone-history")
    subcommands = root.add_subparsers(dest="command", required=True)
    _ = subcommands.add_parser("serve", help="run the authenticated HTTP service")
    _ = subcommands.add_parser("status", help="print local service status")
    _ = subcommands.add_parser("maintenance", help="retry pending exports and prune attachments")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings.from_environment()
    if args.command == "serve":
        server = build_server(settings)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
        finally:
            server.server_close()
        return 0

    service = PhoneHistoryService(settings)
    payload = service.status() if args.command == "status" else service.maintenance()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0
