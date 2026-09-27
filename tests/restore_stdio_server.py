"""Fresh-process MCP entry point with a deterministic restore-fixture clock."""
import sys
from datetime import datetime, tzinfo
from pathlib import Path
from typing import override

from pydantic import TypeAdapter
from pytest import MonkeyPatch

from sb.config import Config, TomlValue
from tests.json_fixtures import parse_object


def main() -> None:
    import sb.mcp as module

    data = parse_object(Path(sys.argv[1]).read_text())
    timestamp = data['now']
    assert isinstance(timestamp, str)
    now = datetime.fromisoformat(timestamp)

    class Clock(datetime):
        @classmethod
        @override
        def now(cls, tz: tzinfo | None = None) -> datetime:
            del tz
            return now

    MonkeyPatch().setattr(module, "datetime", Clock)
    module.build_server(config=Config(raw=TypeAdapter[dict[str, TomlValue]](dict[str, TomlValue]).validate_python(data['config'], strict=True))).run()


if __name__ == '__main__':
    main()
