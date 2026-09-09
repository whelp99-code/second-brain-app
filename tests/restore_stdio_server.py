"""Fresh-process MCP entry point with a deterministic restore-fixture clock."""
import json
import sys
from datetime import datetime
from pathlib import Path

from sb.config import Config


def main():
    import sb.mcp as module

    data = json.loads(Path(sys.argv[1]).read_text())
    now = datetime.fromisoformat(data['now'])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    module.datetime = Clock
    module.build_server(config=Config(raw=data['config'])).run()


if __name__ == '__main__':
    main()
