"""Copy a bounded standalone Python tree without external filesystem links."""

import hashlib
import json
import os
import runpy
import shutil
import stat
from pathlib import Path


def runtime_digest(root: Path) -> str:
    inventory = runpy.run_path(str(Path(__file__).with_name("check-release-contents.py")))["inventory"]
    # Paths inside the runtime are part of the identity; its staging directory is not.
    entries = inventory(root)["entries"]
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"sb-python-runtime-v1\0" + raw).hexdigest()


def release_identity(wheel: bytes, requirements: bytes, runtime_sha256: str, recipe_sha256: str) -> str:
    payload = {"wheel": hashlib.sha256(wheel).hexdigest(),
               "requirements": hashlib.sha256(requirements).hexdigest(),
               "python_runtime": runtime_sha256, "preparation_recipe": recipe_sha256}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"sb-release-inputs-v3\0" + raw).hexdigest()[:40]


def bundle_runtime(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    size = 0
    for count, path in enumerate(source.rglob("*"), 1):
        if count > 20000:
            raise ValueError("PYTHON_RUNTIME_FILE_BUDGET")
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            if os.path.isabs(os.readlink(path)) or not path.resolve(strict=True).is_relative_to(source):
                raise ValueError("PYTHON_RUNTIME_EXTERNAL_LINK")
        elif stat.S_ISREG(metadata.st_mode):
            size += metadata.st_size
            if size > 1024 * 1024 * 1024:
                raise ValueError("PYTHON_RUNTIME_BYTE_BUDGET")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("PYTHON_RUNTIME_SPECIAL_FILE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
