#!/usr/bin/env python3
"""Record/verify a quiescent installed release; never activates or seals it.

Keep the inventory outside the release and its printed SHA256 independently.
All entries, including bytecode, are covered. External directory links and
special files are rejected. External file links (e.g. Python) are hash-pinned;
their dynamic libraries, configuration and future changes are not constrained.
This is a point-in-time comparison, not protection against concurrent writers.
"""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


def file_digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("RELEASE_SPECIAL_FILE")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_mtime_ns, s.st_ctime_ns)
    if identity(before) != identity(after):
        raise ValueError("RELEASE_FILE_CHANGED_DURING_READ")
    return {"sha256": digest, "size": after.st_size, "mode": stat.S_IMODE(after.st_mode)}


def inventory(root):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("RELEASE_ROOT_NOT_DIRECTORY")
    entries = {".": {"kind": "directory", "mode": stat.S_IMODE(root.stat().st_mode)}}

    def visit(directory):
        for path in sorted(directory.iterdir()):
            metadata = path.lstat()
            key = path.relative_to(root).as_posix()
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                target = path.resolve(strict=True)
                external = not target.is_relative_to(root)
                entry = {"kind": "symlink", "target": os.readlink(path), "mode": mode}
                if external:
                    if not target.is_file():
                        raise ValueError("RELEASE_EXTERNAL_DIRECTORY_LINK")
                    entry["external_file"] = {"path": str(target), **file_digest(target)}
                entries[key] = entry
            elif stat.S_ISDIR(metadata.st_mode):
                entries[key] = {"kind": "directory", "mode": mode}
                visit(path)
            elif stat.S_ISREG(metadata.st_mode):
                entries[key] = {"kind": "file", **file_digest(path)}
            else:
                raise ValueError("RELEASE_SPECIAL_FILE")

    visit(root)
    return {"schema": 1, "root": str(root), "entries": entries}


def verify(root, manifest, expected_sha256):
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("RELEASE_INVENTORY_DIGEST_MISMATCH")
    expected = json.loads(raw)
    actual = inventory(root)
    if expected.get("schema") != 1 or expected.get("root") != actual["root"]:
        raise ValueError("RELEASE_INVENTORY_IDENTITY_MISMATCH")
    old, new = expected["entries"], actual["entries"]
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(key for key in old.keys() & new.keys() if old[key] != new[key])
    return {"matches": not (added or removed or changed), "added": added,
            "removed": removed, "changed": changed, "entries": len(new),
            "activation_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("record", "verify"))
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.manifest.resolve().is_relative_to(args.root.resolve()):
        parser.error("inventory must be outside release")
    if args.operation == "record":
        if args.expected_sha256:
            parser.error("expected SHA256 is only used for verify")
        raw = (json.dumps(inventory(args.root), sort_keys=True, indent=2) + "\n").encode()
        fd = os.open(args.manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
        print(json.dumps({"sha256": hashlib.sha256(raw).hexdigest(),
                          "activation_authorized": False}))
        return 0
    if not args.expected_sha256:
        parser.error("verify requires independently recorded --expected-sha256")
    result = verify(args.root, args.manifest, args.expected_sha256)
    print(json.dumps(result))
    return 0 if result["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
