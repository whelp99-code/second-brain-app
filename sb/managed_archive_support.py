"""Shared inspection errors and isolated, resource-bounded Git pack decoding."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO


class ManagedInspectionError(RuntimeError):
    pass

# No archive configuration, hooks, indexes, refs, alternates or paths are trusted.
# A child interpreter sets limits before exec; preexec_fn is unsafe in the web threads.
_WORKER = """
import os, resource, subprocess, sys
limit = int(sys.argv[1])
resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
subprocess.run(['git', 'index-pack', '--strict', sys.argv[2]], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.execvp('git', ['git', 'cat-file', '--batch-all-objects', '--batch'])
"""


def packed_objects(source: IO[bytes], *, max_bytes: int, max_objects: int) -> Iterator[bytes]:
    """Validate pack checksums/deltas with Git, then expose every (even unreachable) object.

    Only the bounded pack and bounded decoded stream touch a private temporary
    directory. Thin packs cannot resolve against the host repository.
    """
    if max_bytes <= 0 or max_objects <= 0:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    with TemporaryDirectory(prefix="sb-pack-inspection-") as temporary:
        root = Path(temporary)
        packs = root / "objects" / "pack"
        packs.mkdir(parents=True)
        (root / "refs").mkdir()
        _ = (root / "HEAD").write_text("ref: refs/heads/unused\n")
        pack = packs / ("pack-" + "0" * 40 + ".pack")
        size = 0
        with pack.open("wb") as output:
            header = source.read(12)
            if (len(header) != 12 or header[:4] != b"PACK"
                    or int.from_bytes(header[4:8], "big") not in (2, 3)):
                raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
            count = int.from_bytes(header[8:12], "big")
            if count > max_objects:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            _ = output.write(header)
            size += len(header)
            while block := source.read(65_536):
                size += len(block)
                if size > max_bytes:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                _ = output.write(block)
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_DIR=str(root), GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_SYSTEM=os.devnull, GIT_NO_REPLACE_OBJECTS="1")
        with (root / "decoded").open("w+b") as decoded:
            try:
                result = subprocess.run(
                    [sys.executable, "-I", "-c", _WORKER, str(max_bytes), str(pack)],
                    cwd=root, env=env, stdout=decoded, stderr=subprocess.DEVNULL,
                    timeout=90, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET") from exc
            if result.returncode != 0:
                raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
            _ = decoded.seek(0)
            for _ in range(count):
                fields = decoded.readline(128).split()
                if len(fields) != 3 or not fields[2].isdigit():
                    raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
                length = int(fields[2])
                if length > min(max_bytes, 64 * 1024**2):
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                payload = decoded.read(length)
                if len(payload) != length or decoded.read(1) != b"\n":
                    raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
                yield payload
            if decoded.read(1):
                raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
