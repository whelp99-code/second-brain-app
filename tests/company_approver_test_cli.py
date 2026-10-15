"""Run the actual CLI with the shared provider and explicit test clock only."""

from __future__ import annotations

import sys
from pathlib import Path

import sb.company_memory_cli as cli
from sb.effect_values import parse_instant
from tests.company_approver_test_runtime import provider_for_config


def main() -> int:
    arguments = sys.argv[1:]
    clock = arguments.index("--test-now")
    instant = parse_instant(arguments[clock + 1])
    del arguments[clock : clock + 2]
    config_path = Path(arguments[arguments.index("--config") + 1])
    provider, observed = provider_for_config(config_path)
    return cli.main(
        arguments, freshness_provider=provider, observed_checkpoint=observed, now=instant
    )


if __name__ == "__main__":
    raise SystemExit(main())
