"""Private, bounded staging of archived Git packs for the existing object inspector."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from sb.managed_git import inspect_git_directory
from sb.managed_inspection_stream import ManagedInspectionError

MAX_PACK_BYTES: Final = 64 * 1024**2
_PACK_NAME: Final = re.compile(r"pack-[0-9a-f]{40}\.(?:pack|idx)")


@dataclass(frozen=True, slots=True)
class PackMember:
    repository: str
    name: str
    payload: bytes


def inspect_packs(
    members: Sequence[PackMember], needles: Sequence[bytes], decoded: Callable[[bytes], int],
) -> int:
    """Never extract archive paths, config, refs, hooks, or alternates into Git's context."""
    if len(members) > 256:
        raise ManagedInspectionError("MANAGED_GIT_BUDGET")
    groups: dict[str, list[PackMember]] = {}
    for member in members:
        if _PACK_NAME.fullmatch(member.name) is None:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        groups.setdefault(member.repository, []).append(member)
    matches = 0
    with TemporaryDirectory(prefix=".sb-archive-git-") as temporary:
        for index, group in enumerate(groups.values()):
            root = Path(temporary) / str(index)
            folder = root / "objects/pack"
            folder.mkdir(parents=True, mode=0o700)
            (root / "refs").mkdir(mode=0o700)
            _ = (root / "HEAD").write_bytes(b"ref: refs/heads/inspection\n")
            for member in group:
                # Exclusive creation rejects duplicate entries even with equal bytes.
                with (folder / member.name).open("xb") as output:
                    _ = output.write(member.payload)
            matches += inspect_git_directory(root, needles, decoded=decoded).matches
    return matches
