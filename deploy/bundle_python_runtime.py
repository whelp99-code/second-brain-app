"""Copy a bounded standalone Python tree without external filesystem links."""

import os
import shutil
import stat
from pathlib import Path


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
