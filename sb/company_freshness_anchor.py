"""Witness spool and NV extend anchor. Production TPM commands are not invoked here."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Final, Protocol

from sb.effect_values import JsonObject, canonical_bytes

FIXED_REGISTRY_PATH: Final = Path("/etc/second-brain-company/freshness-registry.json")
FIXED_WITNESS_DIR: Final = Path("/var/lib/second-brain-company-freshness/witness")
FIXED_LOCK_PATH: Final = Path("/var/lib/second-brain-company-freshness/registry.lock")
NV_HANDLE: Final = "0x01804F43"
NV_NAME_ALG: Final = "sha256"


class AnchorRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code: str = code


class NvAnchor(Protocol):
    def identity(self) -> str: ...

    def public_name(self) -> bytes: ...

    def read_value(self) -> bytes: ...

    def extend(self, record_digest_raw: bytes) -> bytes: ...


def nv_public_is_extend_only(attributes: frozenset[str]) -> bool:
    if (
        "nt=extend" not in attributes
        or "policydelete" not in attributes
        or "written" not in attributes
    ):
        return False
    return "nt=ordinary" not in attributes and "uninitialized" not in attributes


def tpm_nvextend_argv(handle: str) -> list[str]:
    if handle != NV_HANDLE:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return ["tpm2_nvextend", "-C", "o", "-i-", handle]


def tpm_nvread_argv(handle: str, output: Path) -> list[str]:
    if handle != NV_HANDLE:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return ["tpm2_nvread", "-C", "o", "-o", str(output), "-s", "32", handle]


def tpm_nvreadpublic_argv() -> list[str]:
    return ["tpm2_nvreadpublic"]


def parse_nvreadpublic(text: str, handle: str = NV_HANDLE) -> dict[str, str]:
    blocks = _yaml_blocks(text)
    matches = [
        block
        for key, block in blocks.items()
        if key.startswith("0x") and int(key, 16) == int(handle, 16)
    ]
    if len(matches) != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    block = matches[0]
    friendly = block.get("attributes.friendly", "")
    tokens = frozenset(part.strip() for part in friendly.split("|") if part.strip())
    if not nv_public_is_extend_only(tokens):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if block.get("hash algorithm.friendly") != "sha256" or block.get("size") != "32":
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    name = block.get("name")
    if name is None or any(character not in "0123456789abcdef" for character in name):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return {
        "handle": handle,
        "attributes": friendly,
        "hash_algorithm": "sha256",
        "size": "32",
        "name": name,
    }


def require_trusted_file(path: Path, *, mode: int) -> None:
    _trusted_parents(path)
    if path.is_symlink():
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if info.st_uid != os.geteuid() and info.st_uid != 0:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if stat.S_IMODE(info.st_mode) != mode:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if path == FIXED_REGISTRY_PATH and info.st_uid != 0:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def require_trusted_dir(path: Path) -> None:
    _trusted_parents(path)
    if path.is_symlink() or not path.is_dir():
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if path.parent.is_symlink():
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    stat = path.stat()
    if stat.st_uid != os.geteuid() and stat.st_uid != 0:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    if stat.st_mode & 0o777 != 0o700:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _trusted_parents(path: Path) -> None:
    if not path.is_absolute():
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        shared_sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if info.st_mode & 0o022 and not shared_sticky:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def frame_line(body: JsonObject) -> bytes:
    checksum = hashlib.sha256(canonical_bytes(body)).hexdigest()
    full: JsonObject = {**body, "checksum": checksum}
    return canonical_bytes(full) + b"\n"


def append_witness_frame(witness_dir: Path, body: JsonObject) -> None:
    require_trusted_dir(witness_dir)
    path = witness_dir / "frames.jsonl"
    payload = frame_line(body)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid not in {0, os.geteuid()}
        ):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        offset = info.st_size
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                written += count
            os.fsync(descriptor)
        except (OSError, AnchorRejected):
            os.ftruncate(descriptor, offset)
            os.fsync(descriptor)
            raise
    finally:
        os.close(descriptor)
    require_trusted_file(path, mode=0o600)
    directory = os.open(witness_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_witness_frames(witness_dir: Path) -> list[JsonObject]:
    require_trusted_dir(witness_dir)
    path = witness_dir / "frames.jsonl"
    if not path.exists():
        return []
    require_trusted_file(path, mode=0o600)
    frames: list[JsonObject] = []
    for line in path.read_bytes().splitlines():
        if not line:
            continue
        from sb.effect_values import strict_loads

        loaded = strict_loads(line, 1_000_000)
        if not isinstance(loaded, dict):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        checksum = loaded.get("checksum")
        body = {key: value for key, value in loaded.items() if key != "checksum"}
        if checksum != hashlib.sha256(canonical_bytes(body)).hexdigest():
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        frames.append(body)
    return frames


def _yaml_blocks(text: str) -> dict[str, dict[str, str]]:
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    stack: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0 and line.endswith(":") and " " not in line[:-1]:
            current = {}
            blocks[line[:-1]] = current
            stack = [(0, "")]
            continue
        if current is None or ":" not in line:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        key, value = line.split(":", 1)
        while stack and stack[-1][0] >= indent:
            _ = stack.pop()
        prefix = ".".join(item[1] for item in stack if item[1])
        full = f"{prefix}.{key}" if prefix else key
        if value.strip():
            current[full] = value.strip()
        stack.append((indent, key))
    return blocks


def extend_if_needed(anchor: NvAnchor, previous: bytes, nxt: bytes, record_raw: bytes) -> None:
    live = anchor.read_value()
    if live == nxt:
        return
    if live != previous:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    updated = anchor.extend(record_raw)
    if updated != nxt or anchor.read_value() != nxt:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
