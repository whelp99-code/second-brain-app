"""Copy trace-observed uv cache inputs; validate completeness with an offline build."""

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
from pathlib import Path


def snapshot_cache(trace: Path, cache: Path, destination: Path) -> dict:
    cache = cache.resolve(strict=True)
    if os.path.lexists(destination):
        raise ValueError("CACHE_SNAPSHOT_DESTINATION_EXISTS")
    observed = set()
    with trace.open() as stream:
        for line in stream:
            for quoted in re.findall(r'"(?:[^"\\]|\\.)*"', line):
                try:
                    path = Path(json.loads(quoted))
                except ValueError:
                    continue
                if path != cache and path.is_relative_to(cache):
                    observed.add(path)
    if not observed:
        raise ValueError("CACHE_TRACE_HAS_NO_INPUTS")
    for path in observed:
        if path.exists() and not path.resolve().is_relative_to(cache):
            raise ValueError("CACHE_TRACE_ESCAPES_ROOT")
    destination.mkdir(parents=True, mode=0o700)
    archives = {cache.joinpath(*path.relative_to(cache).parts[:2]) for path in observed
                if len(path.relative_to(cache).parts) > 1 and path.relative_to(cache).parts[0] == "archive-v0"}
    for archive in sorted(archives):
        if archive.is_dir():
            shutil.copytree(archive, destination / archive.relative_to(cache), symlinks=True)
    for path in sorted(observed):
        relative = path.relative_to(cache)
        if relative.parts[0] == "archive-v0" or relative.parts[0].startswith(".tmp"):
            continue
        target = destination / relative
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(cache):
                raise ValueError("CACHE_LINK_ESCAPES_ROOT")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.path.relpath(destination / resolved.relative_to(cache), target.parent))
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    inventory = runpy.run_path(str(Path(__file__).with_name("check-release-contents.py")))["inventory"](destination)
    raw = json.dumps(inventory["entries"], sort_keys=True, separators=(",", ":")).encode()
    return {"schema": 1, "cache_entries_sha256": hashlib.sha256(b"sb-offline-cache-v1\0" + raw).hexdigest(),
            "entries": len(inventory["entries"]), "observed_paths": len(observed),
            "archive_roots": len(archives), "offline_completeness_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(snapshot_cache(args.trace, args.cache, args.destination), indent=2))
