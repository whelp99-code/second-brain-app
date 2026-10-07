"""Apply process resource bounds before exec of the managed Git inspection command."""

from __future__ import annotations

import os
import resource
import sys
from typing import Final

MAX_ADDRESS_SPACE: Final = 512 * 1024**2
MAX_CPU_SECONDS: Final = 30


def main() -> None:
    """Bound Git's own decompression allocations, not only the captured stdout."""
    resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_SPACE, MAX_ADDRESS_SPACE))
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
    os.execvp("git", ["git", *sys.argv[1:]])


if __name__ == "__main__":
    main()
